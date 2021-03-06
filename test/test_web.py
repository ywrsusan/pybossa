#-*- coding: utf8 -*-
# This file is part of PYBOSSA.
#
# Copyright (C) 2017 Scifabric LTD.
#
# PYBOSSA is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PYBOSSA is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with PYBOSSA.  If not, see <http://www.gnu.org/licenses/>.

import re
import codecs
import copy
import json
import os
import shutil
import zipfile
from StringIO import StringIO
from default import db, Fixtures, with_context, with_context_settings, FakeResponse, mock_contributions_guard
from helper import web
from mock import patch, Mock, call, MagicMock
from flask import redirect
from itsdangerous import BadSignature
from pybossa.util import get_user_signup_method, unicode_csv_reader
from bs4 import BeautifulSoup
from requests.exceptions import ConnectionError
from pybossa.model.project import Project
from pybossa.model.category import Category
from pybossa.model.task import Task
from pybossa.model.task_run import TaskRun
from pybossa.model.user import User
from pybossa.model.result import Result
from pybossa.messages import *
from pybossa.leaderboard.jobs import leaderboard as update_leaderboard
from pybossa.core import user_repo, project_repo, result_repo, announcement_repo, signer, task_repo
from pybossa.jobs import send_mail, import_tasks
from pybossa.importers import ImportReport
from pybossa.cache.project_stats import update_stats
from pybossa.syncer import NotEnabled, SyncUnauthorized
from factories import AnnouncementFactory, ProjectFactory, CategoryFactory, TaskFactory, TaskRunFactory, UserFactory
from unidecode import unidecode
from werkzeug.utils import secure_filename
from nose.tools import assert_raises
from flatten_json import flatten
from nose.tools import nottest
from helper.gig_helper import make_subadmin, make_subadmin_by
from datetime import datetime, timedelta
import six
from pybossa.view.account import get_user_data_as_form
from pybossa.cloud_store_api.s3 import upload_json_data



class TestWeb(web.Helper):
    pkg_json_not_found = {
        "help": "Return ...",
        "success": False,
        "error": {
            "message": "Not found",
            "__type": "Not Found Error"}}

    patch_data_access_levels = dict(
        valid_access_levels=[("L1", "L1"), ("L2", "L2"),("L3", "L3"), ("L4", "L4")],
        valid_user_levels_for_project_task_level=dict(
            L1=[], L2=["L1"], L3=["L1", "L2"], L4=["L1", "L2", "L3"]),
        valid_task_levels_for_user_level=dict(
            L1=["L2", "L3", "L4"], L2=["L3", "L4"], L3=["L4"], L4=[]),
        valid_project_levels_for_task_level=dict(
            L1=["L1"], L2=["L1", "L2"], L3=["L1", "L2", "L3"], L4=["L1", "L2", "L3", "L4"]),
        valid_task_levels_for_project_level=dict(
            L1=["L1", "L2", "L3", "L4"], L2=["L2", "L3", "L4"], L3=["L3", "L4"], L4=["L4"])
    )

    def clear_temp_container(self, user_id):
        """Helper function which deletes all files in temp folder of a given owner_id"""
        temp_folder = os.path.join('/tmp', 'user_%d' % user_id)
        if os.path.isdir(temp_folder):
            shutil.rmtree(temp_folder)

    @with_context
    def test_01_index(self):
        """Test WEB home page works"""
        self.register(name="juan")
        self.signin(email="juan@example.com", password="p4ssw0rd")
        res = self.app.get("/", follow_redirects=True)
        assert self.html_title() in res.data, res.data
        assert "Create" in res.data, res

    @with_context
    def test_01_index_json(self):
        """Test WEB JSON home page works"""
        project = ProjectFactory.create(featured=True)
        res = self.app_get_json("/")
        data = json.loads(res.data)
        keys = ['featured', 'template']
        for key in keys:
            assert key in data.keys(), data
        assert len(data['featured']) == 1, data
        assert data['featured'][0]['short_name'] == project.short_name


    @with_context
    def test_01_search(self):
        """Test WEB search page works."""
        self.register(name="juan")
        self.signin(email="juan@example.com", password="p4ssw0rd")
        res = self.app.get('/search')
        err_msg = "Search page should be accessible"
        assert "Search" in res.data, err_msg

    @with_context
    def test_01_search_json(self):
        """Test WEB JSON search page works."""
        res = self.app_get_json('/search')
        err_msg = "Search page should be accessible"
        data = json.loads(res.data)
        assert data.get('template') == '/home/search.html', err_msg


    @with_context
    def test_result_view(self):
        """Test WEB result page works."""
        import os
        APP_ROOT = os.path.dirname(os.path.abspath(__file__))
        template_folder = os.path.join(APP_ROOT, '..', 'pybossa',
                                       self.flask_app.template_folder)
        file_name = os.path.join(template_folder, "home", "_results.html")
        with open(file_name, "w") as f:
            f.write("foobar")
        self.register(name="juan")
        self.signin(email="juan@example.com", password="p4ssw0rd")
        res = self.app.get('/results')
        assert "foobar" in res.data, res.data
        os.remove(file_name)


    @with_context
    def test_result_view_json(self):
        """Test WEB JSON result page works."""
        import os
        APP_ROOT = os.path.dirname(os.path.abspath(__file__))
        template_folder = os.path.join(APP_ROOT, '..', 'pybossa',
                                       self.flask_app.template_folder)
        file_name = os.path.join(template_folder, "home", "_results.html")
        with open(file_name, "w") as f:
            f.write("foobar")
        res = self.app_get_json('/results')
        data = json.loads(res.data)
        assert data.get('template') == '/home/_results.html', data
        os.remove(file_name)


    @with_context
    def test_00000_results_not_found(self):
        """Test WEB results page returns 404 when no template is found works."""
        res = self.app.get('/results')
        assert res.status_code == 404, res.status_code

    @with_context
    def test_leaderboard(self):
        """Test WEB leaderboard works"""
        user = UserFactory.create()
        self.signin_user(user)
        TaskRunFactory.create(user=user)
        update_leaderboard()
        res = self.app.get('/leaderboard', follow_redirects=True)
        assert self.html_title("Community Leaderboard") in res.data, res
        assert user.name in res.data, res.data
        assert_raises(ValueError, json.loads, res.data)

    @with_context
    def test_leaderboard_json(self):
        """Test leaderboard json works"""
        user = UserFactory.create()
        self.signin_user(user)
        TaskRunFactory.create(user=user)
        TaskRunFactory.create(user=user)
        update_leaderboard()
        res = self.app_get_json('/leaderboard/')
        data = json.loads(res.data)
        err_msg = 'Template wrong'
        assert data['template'] == '/stats/index.html', err_msg
        err_msg = 'Title wrong'
        assert data['title'] == 'Community Leaderboard', err_msg
        err_msg = 'Top users missing'
        assert 'top_users' in data, err_msg
        err_msg = 'leaderboard user information missing'
        first_user = data['top_users'][0]
        assert 'created' in first_user, err_msg
        assert first_user['fullname'] == 'User 1', err_msg
        assert first_user['name'] == 'user1', err_msg
        assert first_user['rank'] == 1, err_msg
        assert first_user['score'] == 2, err_msg
        assert 'registered_ago' in first_user, err_msg
        assert 'n_answers' in first_user, err_msg
        assert 'info' in first_user, err_msg
        assert 'avatar' in first_user['info'], err_msg
        assert 'container' in first_user['info'], err_msg
        err_msg = 'privacy leak in user information'
        assert 'id' not in first_user, err_msg
        assert 'api_key' not in first_user, err_msg

        users = UserFactory.create_batch(40)
        for u in users[0:22]:
            TaskRunFactory.create(user=u)
            TaskRunFactory.create(user=u)
            TaskRunFactory.create(user=u)
            TaskRunFactory.create(user=u)

        for u in users[22:28]:
            TaskRunFactory.create(user=u)
            TaskRunFactory.create(user=u)
            TaskRunFactory.create(user=u)

        update_leaderboard()

        for score in range(1, 11):
            UserFactory.create(info=dict(n=score))

        update_leaderboard(info='n')

        res = self.app_get_json('/leaderboard/window/3?api_key=%s' % user.api_key)
        data = json.loads(res.data)
        err_msg = 'Top users missing'
        assert 'top_users' in data, err_msg
        err_msg = 'leaderboard user information missing'
        leaders = data['top_users']
        assert len(leaders) == (20+3+1+3), len(leaders)
        assert leaders[23]['name'] == user.name

        res = self.app_get_json('/leaderboard/window/11?api_key=%s' % user.api_key)
        data = json.loads(res.data)
        err_msg = 'Top users missing'
        assert 'top_users' in data, err_msg
        err_msg = 'leaderboard user information missing'
        leaders = data['top_users']
        assert len(leaders) == (20+10+1+10), len(leaders)
        assert leaders[30]['name'] == user.name

        res = self.app_get_json('/leaderboard/?info=noleaderboards')
        assert res.status_code == 404,  res.status_code

        with patch.dict(self.flask_app.config, {'LEADERBOARDS': ['n']}):
            res = self.app_get_json('/leaderboard/?info=n')
            data = json.loads(res.data)
            err_msg = 'Top users missing'
            assert 'top_users' in data, err_msg
            err_msg = 'leaderboard user information missing'
            leaders = data['top_users']
            assert len(leaders) == (21), len(leaders)
            score = 10
            rank = 1
            for u in leaders[0:10]:
                assert u['score'] == score, u
                assert u['rank'] == rank, u
                score = score - 1
                rank = rank + 1

            res = self.app_get_json('/leaderboard/window/3?api_key=%s&info=n' % user.api_key)
            data = json.loads(res.data)
            err_msg = 'Top users missing'
            assert 'top_users' in data, err_msg
            err_msg = 'leaderboard user information missing'
            leaders = data['top_users']
            assert len(leaders) == (20+3+1+3), len(leaders)
            assert leaders[23]['name'] == user.name
            assert leaders[23]['score'] == 0

            res = self.app_get_json('/leaderboard/?info=new')
            assert res.status_code == 404,  res.status_code


    @with_context
    def test_announcement_json(self):
        """Test public announcements"""
        url = '/announcements/'
        err_msg = "It should return 200"
        res = self.app_get_json(url)
        data = json.loads(res.data)
        assert res.status_code == 200, err_msg
        assert "announcements" in data.keys(), data
        assert "template" in data.keys(), data
        # create an announcement in DB
        announcement = AnnouncementFactory.create()
        res = self.app_get_json(url)
        data = json.loads(res.data)
        announcement0 = data['announcements'][0]
        assert announcement0['body'] == 'Announcement body text'
        assert announcement0['title'] == 'Announcement title'
        assert announcement0['id'] == 1

    @with_context
    def test_project_stats(self):
        """Test WEB project stats page works"""
        res = self.register()
        res = self.signin()
        res = self.new_project(short_name="igil")

        project = db.session.query(Project).first()
        user = db.session.query(User).first()
        # Without stats
        url = '/project/%s/stats' % project.short_name
        res = self.app.get(url)
        assert "Sorry" in res.data, res.data

        # We use a string here to check that it works too
        task = Task(project_id=project.id, n_answers=10)
        db.session.add(task)
        db.session.commit()

        for i in range(10):
            task_run = TaskRun(project_id=project.id, task_id=1,
                               user_id=user.id,
                               info={'answer': 1})
            db.session.add(task_run)
            db.session.commit()
            res = self.app.get('api/project/%s/newtask' % project.id)

        # With stats
        url = '/project/%s/stats' % project.short_name
        update_stats(project.id)
        res = self.app.get(url)
        assert res.status_code == 200, res.status_code
        assert "Distribution" in res.data, res.data

    @with_context
    def test_project_stats_json(self):
        """Test WEB project stats page works JSON"""
        res = self.register()
        res = self.signin()
        res = self.new_project(short_name="igil")

        project = db.session.query(Project).first()
        user = db.session.query(User).first()
        # Without stats
        url = '/project/%s/stats' % project.short_name
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = 'Field should not be present'
        assert 'avg_contrib_time' not in data, err_msg
        assert 'projectStats' not in data, err_msg
        assert 'userStats' not in data, err_msg
        err_msg = 'Field should be present'
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        err_msg = 'Field should not be private'
        assert 'id' in data['owner'], err_msg
        assert res.status_code == 200, res.status_code

        # We use a string here to check that it works too
        task = Task(project_id=project.id, n_answers=10)
        db.session.add(task)
        db.session.commit()

        for i in range(10):
            task_run = TaskRun(project_id=project.id, task_id=1,
                               user_id=user.id,
                               info={'answer': 1})
            db.session.add(task_run)
            db.session.commit()
            self.app_get_json('api/project/%s/newtask' % project.id)

        # With stats
        update_stats(project.id)

        url = '/project/%s/stats' % project.short_name
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = 'Field missing in JSON response'
        assert 'avg_contrib_time' in data, (err_msg, data.keys())
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'projectStats' in data, err_msg
        assert 'userStats' in data, err_msg
        err_msg = 'Field should not be private'
        assert 'id' in data['owner'], err_msg
        assert res.status_code == 200, res.status_code

        url = '/project/%s/stats' % project.short_name
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = 'Field missing in JSON response'
        assert 'avg_contrib_time' in data, err_msg
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'projectStats' in data, err_msg
        assert 'userStats' in data, err_msg
        err_msg = 'Field should not be private'
        assert 'id' in data['owner'], err_msg
        assert res.status_code == 200, res.status_code
        err_msg = 'there should not have geo data'
        assert data['userStats'].get('geo') == None, err_msg


    @with_context
    def test_contribution_time_shown_for_admins_for_every_project(self):
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        owner = UserFactory.create(pro=False)
        project = ProjectFactory.create(owner=owner)
        task = TaskFactory.create(project=project)
        TaskRunFactory.create(task=task)
        update_stats(project.id)
        url = '/project/%s/stats' % project.short_name
        self.signin(email=admin.email_addr, password='1234')
        res = self.app.get(url)
        assert_raises(ValueError, json.loads, res.data)
        assert 'Average contribution time' in res.data


    @with_context
    def test_contribution_time_shown_for_admins_for_every_project_json(self):
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        owner = UserFactory.create(pro=False)
        project = ProjectFactory.create(owner=owner)
        task = TaskFactory.create(project=project)
        TaskRunFactory.create(task=task)
        url = '/project/%s/stats' % project.short_name
        self.signin(email=admin.email_addr, password='1234')
        update_stats(project.id)
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = 'Field missing in JSON response'
        assert 'avg_contrib_time' in data, err_msg
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'projectStats' in data, err_msg
        assert 'userStats' in data, err_msg
        err_msg = 'Field should be private'
        assert 'id' not in data['owner'], err_msg
        assert 'api_key' not in data['owner'], err_msg
        assert 'secret_key' not in data['project'], err_msg


    @with_context
    def test_contribution_time_shown_in_pro_owned_projects(self):
        pro_owner = UserFactory.create(pro=True)
        pro_owner.set_password('1234')
        pro_owned_project = ProjectFactory.create(owner=pro_owner)
        task = TaskFactory.create(project=pro_owned_project)
        TaskRunFactory.create(task=task)
        update_stats(task.project.id)
        pro_url = '/project/%s/stats' % pro_owned_project.short_name
        self.signin(email=pro_owner.email_addr, password='1234')
        res = self.app.get(pro_url)
        assert_raises(ValueError, json.loads, res.data)
        assert 'Average contribution time' in res.data

    @with_context
    def test_contribution_time_shown_in_pro_owned_projects_json(self):
        pro_owner = UserFactory.create(pro=True)
        pro_owned_project = ProjectFactory.create(owner=pro_owner)
        task = TaskFactory.create(project=pro_owned_project)
        TaskRunFactory.create(task=task)
        update_stats(task.project.id)
        pro_url = '/project/%s/stats' % pro_owned_project.short_name

        self.signin_user()
        self.set_proj_passwd_cookie(pro_owned_project, username='user3')
        res = self.app_get_json(pro_url)
        data = json.loads(res.data)
        err_msg = 'Field missing in JSON response'
        assert 'avg_contrib_time' in data, err_msg
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'projectStats' in data, err_msg
        assert 'userStats' in data, err_msg
        err_msg = 'Field should be private'
        assert 'id' not in data['owner'], err_msg
        assert 'api_key' not in data['owner'], err_msg
        assert 'secret_key' not in data['project'], err_msg

    @with_context
    def test_contribution_time_not_shown_in_regular_user_owned_projects(self):
        project = ProjectFactory.create()
        task = TaskFactory.create(project=project)
        TaskRunFactory.create(task=task)
        url = '/project/%s/stats' % project.short_name
        res = self.app.get(url)
        assert_raises(ValueError, json.loads, res.data)
        assert 'Average contribution time' not in res.data

    @with_context
    def test_contribution_time_not_shown_in_regular_user_owned_projects_json(self):
        project = ProjectFactory.create()
        task = TaskFactory.create(project=project)
        TaskRunFactory.create(task=task)
        self.signin_user()
        self.set_proj_passwd_cookie(project, username='user3')
        url = '/project/%s/stats' % project.short_name

        update_stats(project.id)

        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = ('Field missing in JSON response', data)
        assert 'avg_contrib_time' in data, err_msg
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'projectStats' in data, err_msg
        assert 'userStats' in data, err_msg
        err_msg = ('Field should be private', data)
        assert 'id' not in data['owner'], err_msg
        assert 'api_key' not in data['owner'], err_msg
        assert 'secret_key' not in data['project'], err_msg

    @with_context
    def test_03_account_index(self):
        """Test WEB account index works."""
        # Without users
        self.register()
        self.signin()
        res = self.app.get('/account/page/15', follow_redirects=True)
        assert res.status_code == 404, res.data

        self.create()
        res = self.app.get('/account', follow_redirects=True)
        assert res.status_code == 200, res.status_code
        err_msg = "There should be a Community page"
        assert "Community" in res.data, err_msg

    @with_context
    def test_03_account_index_json(self):
        """Test WEB account index JSON works."""
        # Without users
        self.register()
        self.signin()
        res = self.app.get('/account/page/15',
                           content_type='application/json')
        assert res.status_code == 404, res.status_code
        data = json.loads(res.data)
        assert data['code'] == 404, res.status_code

        self.create()
        res = self.app_get_json('/account/')
        data = json.loads(res.data)
        assert res.status_code == 200, res.status_code
        err_msg = "There should be a Community page"
        assert data['title'] == 'Community', err_msg
        err_msg = "There should be a next, prev item in pagination"
        assert data['pagination']['next'] is False, err_msg
        assert data['pagination']['prev'] is False, err_msg
        assert data['pagination']['per_page'] == 24, err_msg
        # page 1 should also work
        res = self.app_get_json('/account/page/1')
        data = json.loads(res.data)
        assert res.status_code == 200, res.status_code
        err_msg = "There should be a Community page"
        assert data['title'] == 'Community', err_msg
        err_msg = "There should be a next, prev item in pagination"
        assert data['pagination']['next'] is False, err_msg
        assert data['pagination']['prev'] is False, err_msg
        assert data['pagination']['per_page'] == 24, err_msg


    @with_context
    def test_register_get(self):
        """Test WEB register user works"""
        self.register(fullname="juan", name="juan")
        self.signin(email="juan@example.com", password="p4ssw0rd")
        res = self.app.get('/account/register')
        # The output should have a mime-type: text/html
        assert res.mimetype == 'text/html', res
        assert self.html_title("Register") in res.data, res

    @with_context
    def test_register_get_json(self):
        """Test WEB register JSON user works"""
        from pybossa.forms.account_view_forms import RegisterForm
        self.register()
        self.signin()
        res = self.app.get('/account/register',
                           content_type='application/json')
        data = json.loads(res.data)

        form = RegisterForm()
        expected_fields = form.data.keys()

        err_msg = "There should be a form"
        assert data.get('form'), err_msg
        for field in expected_fields:
            err_msg = "%s form field is missing"
            if (field != 'confirm' and field != 'password'):
                assert field in data.get('form').keys(), err_msg
        err_msg = "There should be a CSRF field"
        assert data.get('form').get('csrf'), err_msg
        err_msg = "There should be no errors"
        assert data.get('form').get('errors') == {}, err_msg
        err_msg = "There should be a template field"
        assert data.get('template') == 'account/register.html', err_msg
        err_msg = "There should be a title"
        assert data.get('title') == 'Register', err_msg


    @with_context
    def test_register_errors_get(self):
        """Test WEB register errors works"""
        userdict = {'fullname': 'a', 'name': 'name',
                    'email_addr': None, 'password':'p'}
        self.register(fullname="juan", name="juan")
        self.signin(email="juan@example.com", password="p4ssw0rd")
        res = self.app.post('/account/register', data=userdict)
        # The output should have a mime-type: text/html
        assert res.mimetype == 'text/html', res
        assert "correct the errors" in res.data, res.data


    @with_context
    def test_register_wrong_content_type(self):
        """Test WEB Register JSON wrong content type."""
        self.register()
        self.signin()
        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            url = '/account/register'
            csrf = self.get_csrf(url)
            userdict = {'fullname': 'a', 'name': 'name',
                       'email_addr': None, 'password': 'p'}

            res = self.app.post('/account/register', data=userdict,
                                content_type='application/json',
                                headers={'X-CSRFToken': csrf})
            errors = json.loads(res.data)
            assert errors.get('status') == ERROR, errors
            assert not errors.get('form').get('name'), errors
            assert len(errors.get('form').get('errors').get('email_addr')) > 0, errors

            res = self.app_post_json(url, data="{stringoftext")
            data = json.loads(res.data)
            err_msg = "The browser (or proxy) sent a request that this server could not understand."
            assert res.status_code == 400, data
            assert data.get('code') == 400, data
            assert data.get('description') == err_msg, data

            data = json.dumps(userdict)
            data += "}"
            res = self.app.post('/account/register', data=data,
                                content_type='application/json',
                                headers={'X-CSRFToken': csrf})
            data = json.loads(res.data)
            assert res.status_code == 400, data
            assert data.get('code') == 400, data
            assert data.get('description') == err_msg, data

    @with_context
    def test_register_csrf_missing(self):
        """Test WEB Register JSON CSRF token missing."""
        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            userdict = {'fullname': 'a', 'name': 'name',
                       'email_addr': None, 'password': 'p'}

            res = self.app.post('/account/register', data=json.dumps(userdict),
                                content_type='application/json')
            errors = json.loads(res.data)
            err_msg = "The CSRF token is missing."
            assert errors.get('description') == err_msg, err_msg
            err_msg = "Error code should be 400"
            assert errors.get('code') == 400, err_msg
            assert res.status_code == 400, err_msg


    @with_context
    def test_register_csrf_wrong(self):
        """Test WEB Register JSON CSRF token wrong."""
        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            userdict = {'fullname': 'a', 'name': 'name',
                       'email_addr': None, 'password': 'p'}

            res = self.app.post('/account/register', data=json.dumps(userdict),
                                content_type='application/json',
                                headers={'X-CSRFToken': 'wrong'})
            errors = json.loads(res.data)
            err_msg = "The CSRF session token is missing."
            assert errors.get('description') == err_msg, err_msg
            err_msg = "Error code should be 400"
            assert errors.get('code') == 400, err_msg
            assert res.status_code == 400, err_msg


    @with_context
    def test_register_json_errors_get(self):
        """Test WEB register errors JSON works"""
        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            self.gig_account_creator_register_signin(with_csrf=True)
            csrf = self.get_csrf('/account/register')

            userdict = {'fullname': 'a', 'name': 'name',
                        'email_addr': None}

            res = self.app.post('/account/register', data=json.dumps(userdict),
                                content_type='application/json',
                                headers={'X-CSRFToken': csrf})
            # The output should have a mime-type: application/json
            errors = json.loads(res.data).get('form').get('errors')
            assert res.mimetype == 'application/json', res.data
            err_msg = "There should be an error with the email"
            assert errors.get('email_addr'), err_msg
            err_msg = "There should be an error with fullname"
            assert errors.get('fullname'), err_msg
            err_msg = "There should NOT be an error with name"
            assert errors.get('name') is None, err_msg


    @with_context
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.render_template')
    @patch('pybossa.view.account.signer')
    def test_register_post_creates_email_with_link(self, signer, render, queue):
        """Test WEB register post creates and sends the confirmation email if
        account validation is enabled"""
        from flask import current_app
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        self.register()
        self.signin()
        signer.dumps.return_value = ''
        render.return_value = ''
        self.update_profile(email_addr="new@mail.com")
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = dict(fullname="John Doe", name="johndoe",
                    email_addr="new@mail.com")

        signer.dumps.assert_called_with(data, salt='account-validation')
        render.assert_any_call('/account/email/validate_email.md',
                               user=data,
                               confirm_url='http://{}/account/register/confirmation?key='.format(
                                self.flask_app.config['SERVER_NAME']))
        assert send_mail == queue.enqueue.call_args[0][0], "send_mail not called"
        mail_data = queue.enqueue.call_args[0][1]
        assert 'subject' in mail_data.keys()
        assert 'recipients' in mail_data.keys()
        assert 'body' in mail_data.keys()
        assert 'html' in mail_data.keys()

    @with_context
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.render_template')
    @patch('pybossa.view.account.signer')
    def test_register_post_json_creates_email_with_link(self, signer, render, queue):
        """Test WEB register post JSON creates and sends the confirmation email if
        account validation is enabled"""
        from flask import current_app
        import app_settings
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        app_settings.upref_mdata = False
        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            self.gig_account_creator_register_signin(with_csrf=True)
            csrf = self.get_csrf('/account/register')
            data = dict(fullname="John Doe", name="johndoe",
                        password="p4ssw0rd", confirm="p4ssw0rd",
                        email_addr="johndoe@example.com",
                        consent=False)
            signer.dumps.return_value = ''
            render.return_value = ''
            res = self.app.post('/account/register', data=json.dumps(data),
                                content_type='application/json',
                                headers={'X-CSRFToken': csrf})
            del data['confirm']
            current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True

            signer.dumps.assert_called_with(data, salt='account-validation')
            render.assert_any_call('/account/email/validate_account.md',
                                   user=data,
                                   confirm_url='http://{}/account/register/confirmation?key='.format(
                                    self.flask_app.config['SERVER_NAME']))
            assert send_mail == queue.enqueue.call_args[0][0], "send_mail not called"
            mail_data = queue.enqueue.call_args[0][1]
            assert 'subject' in mail_data.keys()
            assert 'recipients' in mail_data.keys()
            assert 'body' in mail_data.keys()
            assert 'html' in mail_data.keys()


    @with_context
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.render_template')
    @patch('pybossa.view.account.signer')
    def test_update_email_validates_email(self, signer, render, queue):
        """Test WEB update user email creates and sends the confirmation email
        if account validation is enabled"""
        from flask import current_app
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        self.register()
        self.signin()
        signer.dumps.return_value = ''
        render.return_value = ''
        self.update_profile(email_addr="new@mail.com")
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = dict(fullname="John Doe", name="johndoe",
                    email_addr="new@mail.com")

        signer.dumps.assert_called_with(data, salt='account-validation')
        render.assert_any_call('/account/email/validate_email.md',
                               user=data,
                               confirm_url='http://{}/account/register/confirmation?key='.format(
                                self.flask_app.config['SERVER_NAME']))
        assert send_mail == queue.enqueue.call_args[0][0], "send_mail not called"
        mail_data = queue.enqueue.call_args[0][1]
        assert 'subject' in mail_data.keys()
        assert 'recipients' in mail_data.keys()
        assert 'body' in mail_data.keys()
        assert 'html' in mail_data.keys()
        assert mail_data['recipients'][0] == data['email_addr']
        user = db.session.query(User).get(1)
        msg = "Confirmation email flag not updated"
        assert user.confirmation_email_sent, msg
        msg = "Email not marked as invalid"
        assert user.valid_email is False, msg
        msg = "Email should remain not updated, as it's not been validated"
        assert user.email_addr != 'new@email.com', msg

    @with_context
    def test_register_json(self):
        """Test WEB register JSON creates a new user and logs in."""
        self.register()
        self.signin()
        from flask import current_app
        current_app.config['USER_TYPES'] = [('', ''),('temp', 'temp')]
        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            csrf = self.get_csrf('/account/register')
            data = dict(fullname="John Doe", name="johndoe1", password='daniel',
                        email_addr="new@mail.com", confirm='daniel',
                        consent=True, user_type="temp")
            res = self.app.post('/account/register', data=json.dumps(data),
                                content_type='application/json',
                                headers={'X-CSRFToken': csrf},
                                follow_redirects=False)
            assert res.status_code == 200

    @with_context
    def test_register_json_error(self):
        """Test WEB register JSON does not create a new user
        and does not log in."""
        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            self.gig_account_creator_register_signin(with_csrf=True)
            csrf = self.get_csrf('/account/register')
            data = dict(fullname="John Doe", name="johndoe", email_addr="new@mailcom")
            res = self.app.post('/account/register', data=json.dumps(data),
                                content_type='application/json',
                                headers={'X-CSRFToken': csrf},
                                follow_redirects=False)
            cookie = self.check_cookie(res, 'remember_token')
            err_msg = "User should not be logged in"
            assert cookie is False, err_msg


    @with_context
    def test_confirm_email_returns_404(self):
        """Test WEB confirm_email returns 404 when disabled."""
        self.signin_user()
        res = self.app.get('/account/confirim-email', follow_redirects=True)
        assert res.status_code == 404, res.status_code

    @with_context
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.render_template')
    @patch('pybossa.view.account.signer')
    def test_validate_email(self, signer, render, queue):
        """Test WEB validate email sends the confirmation email
        if account validation is enabled"""
        from flask import current_app
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        self.register()
        self.signin()
        user = db.session.query(User).get(1)
        user.valid_email = False
        db.session.commit()
        signer.dumps.return_value = ''
        render.return_value = ''
        data = dict(fullname=user.fullname, name=user.name,
                    email_addr=user.email_addr)

        res = self.app.get('/account/confirm-email', follow_redirects=True)
        signer.dumps.assert_called_with(data, salt='account-validation')
        render.assert_any_call('/account/email/validate_email.md',
                               user=data,
                               confirm_url='http://{}/account/register/confirmation?key='.format(
                                self.flask_app.config['SERVER_NAME']))
        assert send_mail == queue.enqueue.call_args[0][0], "send_mail not called"
        mail_data = queue.enqueue.call_args[0][1]
        assert 'subject' in mail_data.keys()
        assert 'recipients' in mail_data.keys()
        assert 'body' in mail_data.keys()
        assert 'html' in mail_data.keys()
        assert mail_data['recipients'][0] == data['email_addr']
        user = db.session.query(User).get(1)
        msg = "Confirmation email flag not updated"
        assert user.confirmation_email_sent, msg
        msg = "Email not marked as invalid"
        assert user.valid_email is False, msg
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True

    @with_context
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.render_template')
    @patch('pybossa.view.account.signer')
    def test_validate_email_json(self, signer, render, queue):
        """Test WEB validate email sends the confirmation email
        if account validation is enabled"""
        from flask import current_app
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        self.register()
        user = db.session.query(User).get(1)
        user.valid_email = False
        db.session.commit()
        signer.dumps.return_value = ''
        render.return_value = ''
        data = dict(fullname=user.fullname, name=user.name,
                    email_addr=user.email_addr)

        self.signin()
        res = self.app_get_json('/account/confirm-email')

        signer.dumps.assert_called_with(data, salt='account-validation')
        render.assert_any_call('/account/email/validate_email.md',
                               user=data,
                               confirm_url='http://{}/account/register/confirmation?key='.format(
                                self.flask_app.config['SERVER_NAME']))
        assert send_mail == queue.enqueue.call_args[0][0], "send_mail not called"
        mail_data = queue.enqueue.call_args[0][1]
        assert 'subject' in mail_data.keys()
        assert 'recipients' in mail_data.keys()
        assert 'body' in mail_data.keys()
        assert 'html' in mail_data.keys()
        assert mail_data['recipients'][0] == data['email_addr']
        user = db.session.query(User).get(1)
        msg = "Confirmation email flag not updated"
        assert user.confirmation_email_sent, msg
        msg = "Email not marked as invalid"
        assert user.valid_email is False, msg
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        # JSON validation
        data = json.loads(res.data)
        assert data.get('status') == INFO, data
        assert "An e-mail has been sent to" in data.get('flash'), data
        assert data.get('next') == '/account/' + user.name + "/", data


    @nottest
    @with_context
    def test_register_post_valid_data_validation_enabled(self):
        """Test WEB register post with valid form data and account validation
        enabled"""
        from flask import current_app
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        current_app.config['USER_TYPES'] = [('', ''),('temp', 'temp')]
        data = dict(fullname="John Doe2", name="johndoe2",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="johndoe2@example.com", user_type="temp")
        self.register()
        self.signin()
        res = self.app.post('/account/register', data=data)
        assert "Account validation" in res.data, res
        assert "Just one more step, please" in res.data, res.data
        res = self.signin(email="johndoe2@example.com",password="p4ssw0rd")
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True

        assert_raises(ValueError, json.loads, res.data)

    @with_context
    def test_register_post_valid_data_validation_enabled_json(self):
        """Test WEB register post with valid form data and account validation
        enabled for JSON"""
        from flask import current_app
        email = "jd@there.net"
        self.register(name="jd", email=email)
        self.signin(email=email)
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        current_app.config['USER_TYPES'] = [('', ''),('temp', 'temp')]
        data = dict(fullname="John Doe", name="johndoe",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="johndoe@example.com", user_type="temp")
        res = self.app_post_json('/account/register', data=data)
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = json.loads(res.data)
        assert data['status'] == 'sent'
        assert data['template'] == 'account/account_validation.html'
        assert data['title'] == 'Account validation'

    @with_context
    def test_register_post_valid_data_validation_enabled_wrong_data_json(self):
        """Test WEB register post with valid form data and account validation
        enabled for JSON"""
        from flask import current_app

        self.register()
        self.signin()
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        data = dict(fullname="John Doe", name="johndoe",
                    password="p4ssw0rd", confirm="anotherp4ssw0rd",
                    email_addr="johndoe@example.com")
        res = self.app_post_json('/account/register', data=data)
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = json.loads(res.data)
        assert data['status'] == 'error'

        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        data = dict(fullname="John Doe", name="johndoe",
                    password="p4ssw0rd", confirm="p4ssw0rd")
        res = self.app_post_json('/account/register', data=data)
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = json.loads(res.data)
        assert 'email_addr' in data['form']['errors']
        assert data['status'] == 'error'

        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        data = dict(name="johndoe",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="johndoe@example.com")
        res = self.app_post_json('/account/register', data=data)
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = json.loads(res.data)
        assert 'fullname' in data['form']['errors']
        assert data['status'] == 'error'

        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        data = dict(fullname="John Doe",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="johndoe@example.com")
        res = self.app_post_json('/account/register', data=data)
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = json.loads(res.data)
        assert 'name' in data['form']['errors']
        assert data['status'] == 'error'

        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        data = dict(fullname="John Doe", name="johndoe",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="wrongemail")
        res = self.app_post_json('/account/register', data=data)
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = json.loads(res.data)
        assert data['status'] == 'error'
        assert data['form']['errors']['email_addr'][0] == 'Invalid email address.'

    @with_context
    @patch('pybossa.util.redirect', wraps=redirect)
    def test_register_post_valid_data_validation_disabled(self, mockredirect):
        """Test WEB register post with valid form data and account validation
        disabled redirects to home page"""
        from flask import current_app
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = dict(fullname="John Doe", name="johndoe",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="johndoe@example.com")
        self.register()
        self.signin()
        res = self.app.post('/account/register', data=data)
        print((dir(redirect)))
        mockredirect.assert_called_with('/')

    @with_context
    def test_register_confirmation_fails_without_key(self):
        """Test WEB register confirmation returns 403 if no 'key' param is present"""
        res = self.app.get('/account/register/confirmation')

        assert res.status_code == 403, res.status

    @with_context
    def test_register_confirmation_fails_with_invalid_key(self):
        """Test WEB register confirmation returns 403 if an invalid key is given"""
        res = self.app.get('/account/register/confirmation?key=invalid')

        assert res.status_code == 403, res.status

    @with_context
    @patch('pybossa.view.account.signer')
    def test_register_confirmation_gets_account_data_from_key(self, fake_signer):
        """Test WEB register confirmation gets the account data from the key"""
        exp_time = self.flask_app.config.get('ACCOUNT_LINK_EXPIRATION')
        fake_signer.loads.return_value = dict(fullname='FN', name='name',
                                              email_addr='email',
                                              password='password',
                                              consent=True)
        res = self.app.get('/account/register/confirmation?key=valid-key')

        fake_signer.loads.assert_called_with('valid-key', max_age=exp_time, salt='account-validation')

    @with_context
    @patch('pybossa.view.account.signer')
    def test_register_confirmation_validates_email(self, fake_signer):
        """Test WEB validates email"""
        self.register()
        user = db.session.query(User).get(1)
        user.valid_email = False
        user.confirmation_email_sent = True
        db.session.commit()

        fake_signer.loads.return_value = dict(fullname=user.fullname,
                                              name=user.name,
                                              email_addr=user.email_addr,
                                              consent=False)
        self.app.get('/account/register/confirmation?key=valid-key')

        user = db.session.query(User).get(1)
        assert user is not None
        msg = "Email has not been validated"
        assert user.valid_email, msg
        msg = "Confirmation email flag has not been restored"
        assert user.confirmation_email_sent is False, msg

    @with_context
    @patch('pybossa.view.account.signer')
    def test_register_confirmation_validates_n_updates_email(self, fake_signer):
        """Test WEB validates and updates email"""
        self.register()
        user = db.session.query(User).get(1)
        user.valid_email = False
        user.confirmation_email_sent = True
        db.session.commit()

        fake_signer.loads.return_value = dict(fullname=user.fullname,
                                              name=user.name,
                                              email_addr='new@email.com',
                                              consent=True)
        self.app.get('/account/register/confirmation?key=valid-key')

        user = db.session.query(User).get(1)
        assert user is not None
        msg = "Email has not been validated"
        assert user.valid_email, msg
        msg = "Confirmation email flag has not been restored"
        assert user.confirmation_email_sent is False, msg
        msg = 'Email should be updated after validation.'
        assert user.email_addr == 'new@email.com', msg

    @with_context
    @patch('pybossa.view.account.newsletter', autospec=True)
    @patch('pybossa.view.account.url_for')
    @patch('pybossa.view.account.signer')
    def test_confirm_account_newsletter(self, fake_signer, url_for, newsletter):
        """Test WEB confirm email shows newsletter or home."""
        newsletter.ask_user_to_subscribe.return_value = True
        with patch.dict(self.flask_app.config, {'MAILCHIMP_API_KEY': 'key'}):
            self.register()
            user = db.session.query(User).get(1)
            user.valid_email = False
            db.session.commit()
            url_for.return_value = '/home'
            fake_signer.loads.return_value = dict(fullname=user.fullname,
                                                  name=user.name,
                                                  email_addr=user.email_addr)
            self.app.get('/account/register/confirmation?key=valid-key')

            url_for.assert_called_with('account.newsletter_subscribe', next='/home')

            newsletter.ask_user_to_subscribe.return_value = False
            self.app.get('/account/register/confirmation?key=valid-key')
            url_for.assert_called_with('home.home')

    @with_context
    @patch('pybossa.view.account.newsletter', autospec=True)
    @patch('pybossa.view.account.url_for')
    @patch('pybossa.view.account.signer')
    def test_newsletter_json(self, fake_signer, url_for, newsletter):
        """Test WEB confirm email shows newsletter or home with JSON."""
        newsletter.ask_user_to_subscribe.return_value = True
        with patch.dict(self.flask_app.config, {'MAILCHIMP_API_KEY': 'key'}):
            self.register()
            self.signin()
            user = db.session.query(User).get(1)
            user.valid_email = True
            url = '/account/newsletter'
            res = self.app_get_json(url)
            data = json.loads(res.data)
            assert data.get('title') == 'Subscribe to our Newsletter', data
            assert data.get('template') == 'account/newsletter.html', data


            res = self.app_get_json(url + "?subscribe=True")
            data = json.loads(res.data)
            assert data.get('flash') == 'You are subscribed to our newsletter!', data
            assert data.get('status') == SUCCESS, data


    @with_context
    @patch('pybossa.view.account.signer')
    def test_register_confirmation_creates_new_account(self, fake_signer):
        """Test WEB register confirmation creates the new account"""
        fake_signer.loads.return_value = dict(fullname='FN', name='name',
                                              email_addr='email',
                                              password='password',
                                              consent=False)
        res = self.app.get('/account/register/confirmation?key=valid-key')

        user = db.session.query(User).filter_by(name='name').first()

        assert user is not None
        assert user.check_password('password')

    @with_context
    def test_04_signin_signout_json(self):
        """Test WEB sign in and sign out JSON works"""
        res = self.register()
        # Log out as the registration already logs in the user
        res = self.signout()

        res = self.signin(method="GET", content_type="application/json",
                          follow_redirects=False)
        data = json.loads(res.data)
        err_msg = "There should be a form with two keys email & password"
        csrf = data.get('csrf')
        assert data.get('title') == "Sign in", data
        assert 'email' in data.get('form').keys(), (err_msg, data)
        assert 'password' in data.get('form').keys(), (err_msg, data)

        res = self.signin(email='', content_type="application/json",
                          follow_redirects=False, csrf=csrf)

        data = json.loads(res.data)
        err_msg = "There should be errors in email"
        assert data.get('form').get('errors'), (err_msg, data)
        assert data.get('form').get('errors').get('email'), (err_msg, data)
        msg = "Please correct the errors"
        assert data.get('flash') == msg, (data, err_msg)
        res = self.signin(password='', content_type="application/json",
                          follow_redirects=False, csrf=csrf)
        data = json.loads(res.data)
        assert data.get('flash') == msg, (data, err_msg)
        msg = "You must provide a password"
        assert msg in data.get('form').get('errors').get('password'), (err_msg, data)

        res = self.signin(email='', password='',
                          content_type='application/json',
                          follow_redirects=False,
                          csrf=csrf)
        msg = "Please correct the errors"
        data = json.loads(res.data)
        err_msg = "There should be a flash message"
        assert data.get('flash') == msg, (err_msg, data)
        msg = "The e-mail is required"
        assert data.get('form').get('errors').get('email')[0] == msg, (msg, data)
        msg = "You must provide a password"
        assert data.get('form').get('errors').get('password')[0] == msg, (msg, data)


        # Non-existant user
        msg = "t find you in the system"
        res = self.signin(email='wrongemail', content_type="application/json",
                          follow_redirects=False, csrf=csrf)
        data = json.loads(res.data)
        assert msg in data.get('flash'), (msg, data)
        assert data.get('status') == INFO, (data)

        res = self.signin(email='wrongemail', password='wrongpassword')
        res = self.signin(email='wrongemail', password='wrongpassword',
                          content_type="application/json",
                          follow_redirects=False, csrf=csrf)
        data = json.loads(res.data)
        assert msg in data.get('flash'), (msg, data)
        assert data.get('status') == INFO, (data)

        # Real user but wrong password or username
        msg = "Ooops, Incorrect email/password"
        res = self.signin(password='wrongpassword',
                          content_type="application/json",
                          csrf=csrf,
                          follow_redirects=False)
        data = json.loads(res.data)
        assert msg in data.get('flash'), (msg, data)
        assert data.get('status') == ERROR, (data)

        res = self.signin(content_type="application/json",
                          csrf=csrf, follow_redirects=False)
        data = json.loads(res.data)
        msg = "Welcome back John Doe"
        assert data.get('flash') == msg, (msg, data)
        assert data.get('status') == SUCCESS, (msg, data)
        assert data.get('next') == '/', (msg, data)

        # TODO: add JSON support to profile page.
        # # Check profile page with several information chunks
        # res = self.profile()
        # assert self.html_title("Profile") in res.data, res
        # assert "John Doe" in res.data, res
        # assert "johndoe@example.com" in res.data, res

        # Log out
        res = self.signout(content_type="application/json",
                           follow_redirects=False)
        msg = "You are now signed out"
        data = json.loads(res.data)
        assert data.get('flash') == msg, (msg, data)
        assert data.get('status') == SUCCESS, data
        assert data.get('next') == '/', data

        # TODO: add json to profile public page
        # # Request profile as an anonymous user
        # # Check profile page with several information chunks
        # res = self.profile()
        # assert "John Doe" in res.data, res
        # assert "johndoe@example.com" not in res.data, res

        # Try to access protected areas like update
        res = self.app.get('/account/johndoe/update', follow_redirects=True,
                           content_type="application/json")
        # As a user must be signed in to access, the page the title will be the
        # redirection to log in
        assert self.html_title("Sign in") in res.data, res.data
        assert "This feature requires being logged in." in res.data, res.data

        # TODO: Add JSON to profile
        # res = self.signin(next='%2Faccount%2Fprofile',
        #                   content_type="application/json",
        #                   csrf=csrf)
        # assert self.html_title("Profile") in res.data, res
        # assert "Welcome back %s" % "John Doe" in res.data, res


    @with_context
    def test_04_signin_signout(self):
        """Test WEB sign in and sign out works"""
        res = self.register()
        # Log out as the registration already logs in the user
        res = self.signout()

        res = self.signin(method="GET")
        assert self.html_title("Sign in") in res.data, res.data
        assert "Sign in" in res.data, res.data

        res = self.signin(email='')
        assert "Please correct the errors" in res.data, res
        assert "The e-mail is required" in res.data, res

        res = self.signin(password='')
        assert "Please correct the errors" in res.data, res
        assert "You must provide a password" in res.data, res

        res = self.signin(email='', password='')
        assert "Please correct the errors" in res.data, res
        assert "The e-mail is required" in res.data, res
        assert "You must provide a password" in res.data, res

        # Non-existant user
        msg = "t find you in the system"
        res = self.signin(email='wrongemail')
        assert msg in res.data, res.data

        res = self.signin(email='wrongemail', password='wrongpassword')
        assert msg in res.data, res

        # Real user but wrong password or username
        msg = "Ooops, Incorrect email/password"
        res = self.signin(password='wrongpassword')
        assert msg in res.data, res

        res = self.signin()
        assert self.html_title() in res.data, res
        assert "Welcome back %s" % "John Doe" in res.data, res

        # Check profile page with several information chunks
        res = self.profile()
        #assert self.html_title("Profile") in res.data, res
        assert "John Doe" in res.data, res
        assert "johndoe@example.com" in res.data, res

        # Log out
        res = self.signout()
        assert self.html_title() in res.data, res
        assert "You are now signed out" in res.data, res

        # Request profile as an anonymous user
        # Check profile page with several information chunks
        # res = self.profile()
        # assert "John Doe" in res.data, res
        # assert "johndoe@example.com" not in res.data, res

        # Try to access protected areas like update
        res = self.app.get('/account/johndoe/update', follow_redirects=True)
        # As a user must be signed in to access, the page the title will be the
        # redirection to log in
        assert self.html_title("Sign in") in res.data, res.data
        assert "This feature requires being logged in." in res.data, res.data

        res = self.signin(next='%2Faccount%2Fprofile')
        #assert self.html_title("Profile") in res.data, res
        assert "Welcome back %s" % "John Doe" in res.data, res


    @with_context
    def test_05_test_signout_json(self):
        """Test WEB signout works with json."""
        res = self.app.get('/account/signout',
                           content_type='application/json')
        assert res.status_code == 200, res.status_code
        data = json.loads(res.data)
        err_msg = "next URI is wrong in redirction"
        assert data['next'] == '/', err_msg
        err_msg = "success message missing"
        assert data['status'] == 'success', err_msg


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_profile_applications(self, mock):
        """Test WEB user profile project page works."""
        self.create()
        self.signin(email=Fixtures.email_addr, password=Fixtures.password)
        self.new_project()
        url = '/account/%s/applications' % Fixtures.name
        res = self.app.get(url)
        assert "Projects" in res.data, res.data
        assert "Published" in res.data, res.data
        assert Fixtures.project_name in res.data, res.data

        url = '/account/fakename/applications'
        res = self.app.get(url)
        assert res.status_code == 404, res.status_code

        url = '/account/%s/applications' % Fixtures.name2
        res = self.app.get(url)
        assert res.status_code == 403, res.status_code


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_profile_projects(self, mock):
        """Test WEB user profile project page works."""
        self.create()
        self.signin(email=Fixtures.email_addr, password=Fixtures.password)
        self.new_project()
        url = '/account/%s/projects' % Fixtures.name
        res = self.app.get(url)
        assert "Projects" in res.data, res.data
        assert "Published" in res.data, res.data
        assert Fixtures.project_name in res.data, res.data

        url = '/account/fakename/projects'
        res = self.app.get(url)
        assert res.status_code == 404, res.status_code

        url = '/account/%s/projects' % Fixtures.name2
        res = self.app.get(url)
        assert res.status_code == 403, res.status_code


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_profile_projects_json(self, mock):
        """Test WEB user profile project page works."""
        self.create()
        make_subadmin_by(email_addr=Fixtures.email_addr)
        self.signin(email=Fixtures.email_addr, password=Fixtures.password)
        self.new_project()
        url = '/account/%s/projects' % Fixtures.name
        res = self.app_get_json(url)
        data = json.loads(res.data)
        assert data['title'] == 'Projects', data
        assert data['template'] == 'account/projects.html', data
        assert 'projects_draft' in data, data
        assert 'projects_published' in data, data

        assert data['projects_draft'][0]['id'] == 2
        assert data['projects_published'][0]['id'] == 1
        assert data['projects_published'][0]['name'] == Fixtures.project_name

        url = '/account/fakename/projects'
        res = self.app.get(url)
        assert res.status_code == 404, res.status_code

        url = '/account/%s/projects' % Fixtures.name2
        res = self.app.get(url)
        assert res.status_code == 403, res.status_code


    @with_context
    def test_05_update_user_profile_json(self):
        """Test WEB update user profile JSON"""

        # Create an account and log in
        self.register()
        self.signin()
        url = "/account/fake/update"
        res = self.app.get(url, content_type="application/json")
        data = json.loads(res.data)
        assert res.status_code == 404, res.status_code
        assert data.get('code') == 404, res.status_code

        # Update profile with new data
        res = self.update_profile(method="GET", content_type="application/json")
        data = json.loads(res.data)
        msg = "Update your profile: %s" % "John Doe"
        err_msg = "There should be a title"
        assert data['title'] == msg, err_msg
        err_msg = "There should be 3 forms"
        assert data['form'] is not None, err_msg
        assert data['password_form'] is not None, err_msg
        assert data['upload_form'] is not None, err_msg
        err_msg = "There should be a csrf token"
        assert data['form']['csrf'] is not None, err_msg
        assert data['password_form']['csrf'] is not None, err_msg
        assert data['upload_form']['csrf'] is not None, err_msg

        csrf = data['form']['csrf']

        res = self.update_profile(fullname="John Doe 2",
                                  email_addr="johndoe2@example",
                                  locale="en",
                                  content_type="application/json",
                                  csrf=csrf)
        data = json.loads(res.data)

        err_msg = "There should be errors"
        assert data['form']['errors'] is not None, err_msg
        assert data['form']['errors']['email_addr'] is not None, err_msg

        res = self.update_profile(fullname="John Doe 2",
                                  email_addr="johndoe2@example.com",
                                  locale="en",
                                  content_type="application/json",
                                  csrf=csrf)
        data = json.loads(res.data)
        title = "Update your profile: John Doe 2"
        assert data.get('status') == SUCCESS, res.data
        user = user_repo.get_by(email_addr='johndoe2@example.com')
        url = '/account/%s/update' % user.name
        assert data.get('next') == url, res.data
        flash = u"Your profile has been updated!"
        err_msg = "There should be a flash message"
        assert data.get('flash') == flash, (data, err_msg)
        err_msg = "It should return the same updated data"
        assert "John Doe 2" == user.fullname, user.fullname
        assert "johndoe" == user.name, err_msg
        assert "johndoe2@example.com" == user.email_addr, err_msg
        assert user.subscribed is False, err_msg

        # Updating the username field forces the user to re-log in
        res = self.update_profile(fullname="John Doe 2",
                                  email_addr="johndoe2@example.com",
                                  locale="en",
                                  new_name="johndoe2",
                                  content_type='application/json',
                                  csrf=csrf)
        data = json.loads(res.data)
        err_msg = "Update should work"
        assert data.get('status') == SUCCESS, (err_msg, data)
        url = "/account/johndoe2/update"
        assert data.get('next') == url, (err_msg, data)
        res = self.app.get(url, follow_redirects=False,
                           content_type='application/json')
        assert res.status_code == 302, res.status_code
        assert "/account/signin" in res.data, res.data

        res = self.signin(method="POST", email="johndoe2@example.com",
                          password="p4ssw0rd",
                          next="%2Faccount%2Fprofile")
        assert "Welcome back John Doe 2" in res.data, res.data
        assert "John Doe 2" in res.data, res
        assert "johndoe2" in res.data, res
        assert "johndoe2@example.com" in res.data, res

        res = self.app.get('/', follow_redirects=False)
        assert "::logged-in::johndoe2" in res.data, res.data


        res = self.signout(follow_redirects=False,
                           content_type="application/json")

        data = json.loads(res.data)
        err_msg = "User should be logged out"
        assert not self.check_cookie(res, 'remember_token'), err_msg
        assert data.get('status') == SUCCESS, (err_msg, data)
        assert data.get('next') == '/', (err_msg, data)
        assert "You are now signed out" == data.get('flash'), (err_msg, data)
        res = self.app.get('/', follow_redirects=False)
        assert "::logged-in::johndoe2" not in res.data, err_msg

        # A user must be signed in to access the update page, the page
        # the title will be the redirection to log in
        res = self.update_profile(method="GET", follow_redirects=False,
                                  content_type="application/json")
        err_msg = "User should be requested to log in"
        assert res.status_code == 302, err_msg
        assert "/account/signin" in res.data, err_msg

        self.register(fullname="new", name="new")
        self.signin(email="new@example.com")
        url = "/account/johndoe2/update"
        res = self.app.get(url, content_type="application/json")
        data = json.loads(res.data)
        assert res.status_code == 403
        assert data.get('code') == 403
        assert data.get('description') == FORBIDDEN, data


    @with_context
    def test_05_update_user_profile(self):
        """Test WEB update user profile"""

        # Create an account and log in
        self.register()
        self.signin()
        url = "/account/fake/update"
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 404, res.status_code

        # Update profile with new data
        res = self.update_profile(method="GET")
        msg = "Update your profile: %s" % "John Doe"
        assert self.html_title(msg) in res.data, res.data
        msg = 'input id="id" name="id" type="hidden" value="1"'
        assert msg in res.data, res
        assert "John Doe" in res.data, res
        assert "Save the changes" in res.data, res

        res = self.update_profile(fullname="John Doe 2",
                                  email_addr="johndoe2@example",
                                  locale="en")
        assert "Please correct the errors" in res.data, res.data

        res = self.update_profile(fullname="John Doe 2",
                                  email_addr="johndoe2@example.com",
                                  locale="en")
        title = "Update your profile: John Doe 2"
        assert self.html_title(title) in res.data, res.data
        user = user_repo.get_by(email_addr='johndoe2@example.com')
        assert "Your profile has been updated!" in res.data, res.data
        assert "John Doe 2" in res.data, res
        assert "John Doe 2" == user.fullname, user.fullname
        assert "johndoe" in res.data, res
        assert "johndoe" == user.name, user.name
        assert "johndoe2@example.com" in res.data, res
        assert "johndoe2@example.com" == user.email_addr, user.email_addr
        assert user.subscribed is False, user.subscribed

        # Updating the username field forces the user to re-log in
        res = self.update_profile(fullname="John Doe 2",
                                  email_addr="johndoe2@example.com",
                                  locale="en",
                                  new_name="johndoe2")
        assert "Your profile has been updated!" in res.data, res
        assert "This feature requires being logged in" in res.data, res.data

        res = self.signin(method="POST", email="johndoe2@example.com",
                          password="p4ssw0rd",
                          next="%2Faccount%2Fprofile")
        assert "Welcome back John Doe 2" in res.data, res.data
        assert "John Doe 2" in res.data, res
        assert "johndoe2" in res.data, res
        assert "johndoe2@example.com" in res.data, res

        res = self.signout()
        assert self.html_title() in res.data, res
        assert "You are now signed out" in res.data, res

        # A user must be signed in to access the update page, the page
        # the title will be the redirection to log in
        res = self.update_profile(method="GET")
        assert self.html_title("Sign in") in res.data, res
        assert "This feature requires being logged in." in res.data, res

        # A user must be signed in to access the update page, the page
        # the title will be the redirection to log in
        res = self.update_profile()
        assert self.html_title("Sign in") in res.data, res
        assert "This feature requires being logged in." in res.data, res

        self.register(fullname="new", name="new")
        self.signin(email="new@example.com", password="p4ssw0rd")
        url = "/account/johndoe2/update"
        res = self.app.get(url)
        assert res.status_code == 403

    @with_context
    def test_05a_get_nonexistant_app(self):
        """Test WEB get not existant project should return 404"""
        self.register()
        self.signin()
        res = self.app.get('/project/nonapp', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_05b_get_nonexistant_app_newtask(self):
        """Test WEB get non existant project newtask should return 404"""
        self.register()
        self.signin()
        res = self.app.get('/project/noapp/presenter', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        res = self.app.get('/project/noapp/newtask', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_05c_get_nonexistant_app_tutorial(self):
        """Test WEB get non existant project tutorial should return 404"""
        self.register(fullname="new", name="new")
        self.signin(email="new@example.com", password="p4ssw0rd")
        res = self.app.get('/project/noapp/tutorial', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        res = self.app_get_json('/project/noapp/tutorial')
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_05d_get_nonexistant_app_delete(self):
        """Test WEB get non existant project delete should return 404"""
        self.register()
        self.signin()
        # GET
        res = self.app.get('/project/noapp/delete', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.data
        # POST
        res = self.delete_project(short_name="noapp")
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_05e_get_nonexistant_app_result_status(self):
        """Test WEB get non existant project result status should return 404"""
        self.register()
        self.signin()
        res = self.app.get(
                '/project/noapp/24/result_status',
                follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_project_by_id(self):
        project = ProjectFactory.create(short_name="test")
        url = '/projectid/{}'.format(project.id)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 200

    @with_context
    def test_project_by_id_nonexistant(self):
        url = '/projectid/{}'.format(0)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 404

    @with_context
    def test_delete_project(self):
        """Test WEB JSON delete project."""
        owner = UserFactory.create()
        user = UserFactory.create()
        project = ProjectFactory.create(short_name="algo", owner=owner)
        # As anon
        url = '/project/%s/delete' % project.short_name
        res = self.app_get_json(url, follow_redirects=True)
        assert 'signin' in res.data, res.data

        url = '/project/%s/delete' % project.short_name
        res = self.app_post_json(url)
        assert 'signin' in res.data, res.data

        # As not owner
        url = '/project/%s/delete?api_key=%s' % (project.short_name, user.api_key)
        res = self.app_get_json(url, follow_redirects=True)
        data = json.loads(res.data)
        assert res.status_code == 403, data
        assert data['code'] == 403, data

        url = '/project/%s/delete?api_key=%s' % (project.short_name, user.api_key)
        res = self.app_post_json(url, follow_redirects=True)
        data = json.loads(res.data)
        assert res.status_code == 403, data
        assert data['code'] == 403, data

        # As owner
        url = '/project/%s/delete?api_key=%s' % (project.short_name, owner.api_key)
        res = self.app_get_json(url, follow_redirects=True)
        data = json.loads(res.data)
        assert res.status_code == 200, data
        assert data['project']['name'] == project.name, data

        res = self.app_post_json(url)
        data = json.loads(res.data)
        assert data['status'] == SUCCESS, data
        p = db.session.query(Project).get(project.id)
        assert p is None

    @with_context
    def test_05d_get_nonexistant_project_update(self):
        """Test WEB get non existant project update should return 404"""
        self.register()
        self.signin()
        # GET
        res = self.app.get('/project/noapp/update', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # POST
        res = self.update_project(short_name="noapp")
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_project_upload_thumbnail(self):
        """Test WEB Project upload thumbnail."""
        import io
        owner = UserFactory.create()
        project = ProjectFactory.create(owner=owner)
        url = '/project/%s/update?api_key=%s' % (project.short_name,
                                                 owner.api_key)
        avatar = (io.BytesIO(b'test'), 'test_file.jpg')
        payload = dict(btn='Upload', avatar=avatar,
                       id=project.id, x1=0, y1=0,
                       x2=100, y2=100)
        res = self.app.post(url, follow_redirects=True,
                            content_type="multipart/form-data", data=payload)
        assert res.status_code == 200
        p = project_repo.get(project.id)
        assert p.info['thumbnail'] is not None
        assert p.info['container'] is not None
        thumbnail_url = '%s/uploads/%s/%s' % (self.flask_app.config['SERVER_NAME'],
                                              p.info['container'], p.info['thumbnail'])
        assert p.info['thumbnail_url'].endswith(thumbnail_url)

    @with_context
    def test_account_upload_avatar(self):
        """Test WEB Account upload avatar."""
        import io
        owner = UserFactory.create()
        url = '/account/%s/update?api_key=%s' % (owner.name,
                                                 owner.api_key)
        avatar = (io.BytesIO(b'test'), 'test_file.jpg')
        payload = dict(btn='Upload', avatar=avatar,
                       id=owner.id, x1=0, y1=0,
                       x2=100, y2=100)
        res = self.app.post(url, follow_redirects=True,
                            content_type="multipart/form-data", data=payload)
        assert res.status_code == 200
        u = user_repo.get(owner.id)
        assert u.info['avatar'] is not None
        assert u.info['container'] is not None
        avatar_url = '%s/uploads/%s/%s' % (self.flask_app.config['SERVER_NAME'],
                                           u.info['container'], u.info['avatar'])
        assert u.info['avatar_url'].endswith(avatar_url), u.info['avatar_url']

    @with_context
    def test_05d_get_nonexistant_project_update_json(self):
        """Test WEB JSON get non existant project update should return 404"""
        self.register()
        self.signin()
        # GET
        url = '/project/noapp/update'
        res = self.app_get_json(url)
        data = json.loads(res.data)
        assert res.status == '404 NOT FOUND', res.status
        assert data['code'] == 404, data
        # POST
        res = self.app_post_json(url, data=dict())
        assert res.status == '404 NOT FOUND', res.status
        data = json.loads(res.data)
        assert data['code'] == 404, data

    @with_context
    def test_get_project_json(self):
        """Test WEB JSON get project by short name."""
        project = ProjectFactory.create()
        self.signin_user()
        self.set_proj_passwd_cookie(project, username='user2')
        url = '/project/%s/' % project.short_name
        res = self.app_get_json(url)

        data = json.loads(res.data)['project']

        assert 'id' in data.keys(), data.keys()
        assert 'description' in data.keys(), data.keys()
        assert 'info' in data.keys(), data.keys()
        assert 'long_description' in data.keys(), data.keys()
        assert 'n_tasks' in data.keys(), data.keys()
        assert 'n_volunteers' in data.keys(), data.keys()
        assert 'name' in data.keys(), data.keys()
        assert 'overall_progress' in data.keys(), data.keys()
        assert 'short_name' in data.keys(), data.keys()
        assert 'created' in data.keys(), data.keys()
        assert 'long_description' in data.keys(), data.keys()
        assert 'last_activity' in data.keys(), data.keys()
        assert 'last_activity_raw' in data.keys(), data.keys()
        assert 'n_task_runs' in data.keys(), data.keys()
        assert 'n_results' in data.keys(), data.keys()
        assert 'owner' in data.keys(), data.keys()
        assert 'updated' in data.keys(), data.keys()
        assert 'featured' in data.keys(), data.keys()
        assert 'owner_id' in data.keys(), data.keys()
        assert 'n_completed_tasks' in data.keys(), data.keys()
        assert 'n_blogposts' in data.keys(), data.keys()

    @with_context
    def test_update_project_json_as_user(self):
        """Test WEB JSON update project as user."""
        admin = UserFactory.create()
        owner = UserFactory.create()
        user = UserFactory.create()

        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/update?api_key=%s' % (project.short_name, user.api_key)

        res = self.app_get_json(url)
        data = json.loads(res.data)

        assert data['code'] == 403, data

        old_data = dict()

        old_data['description'] = 'foobar'
        old_data['password'] = 'P4ssw0rd!'

        res = self.app_post_json(url, data=old_data)
        data = json.loads(res.data)

        assert data['code'] == 403, data

    @with_context
    @patch('pybossa.view.projects.cached_projects.clean_project')
    def test_update_project_json_as_admin(self, cache_mock):
        """Test WEB JSON update project as admin."""
        admin = UserFactory.create()
        owner = UserFactory.create()
        user = UserFactory.create()

        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/update?api_key=%s' % (project.short_name, admin.api_key)

        res = self.app_get_json(url)
        data = json.loads(res.data)

        assert data['form']['csrf'] is not None, data
        assert data['upload_form']['csrf'] is not None, data

        old_data = data['form']
        del old_data['csrf']
        del old_data['errors']

        old_data['description'] = 'foobar'
        old_data['password'] = 'P4ssw0rd!'

        res = self.app_post_json(url, data=old_data)
        data = json.loads(res.data)

        assert data['status'] == SUCCESS, data

        u_project = project_repo.get(project.id)
        assert u_project.description == 'foobar', u_project
        cache_mock.assert_called_with(project.id)


    @with_context
    def test_update_project_json_as_owner(self):
        """Test WEB JSON update project."""
        admin = UserFactory.create()
        owner = UserFactory.create()
        user = UserFactory.create()

        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/update?api_key=%s' % (project.short_name, owner.api_key)

        res = self.app_get_json(url)
        data = json.loads(res.data)

        assert data['form']['csrf'] is not None, data
        assert data['upload_form']['csrf'] is not None, data

        old_data = data['form']
        del old_data['csrf']
        del old_data['errors']

        old_data['description'] = 'foobar'
        old_data['password'] = 'P4ssw0rd!'

        res = self.app_post_json(url, data=old_data)
        data = json.loads(res.data)

        assert data['status'] == SUCCESS, data

        u_project = project_repo.get(project.id)
        assert u_project.description == 'foobar', u_project


    @with_context
    def test_update_project_json_as_owner(self):
        """Test WEB JSON update project."""
        admin = UserFactory.create()
        owner = UserFactory.create()
        make_subadmin(owner)
        user = UserFactory.create()

        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/update?api_key=%s' % (project.short_name, owner.api_key)

        res = self.app_get_json(url)
        data = json.loads(res.data)

        assert data['form']['csrf'] is not None, data
        assert data['upload_form']['csrf'] is not None, data

        old_data = data['form']
        del old_data['csrf']
        del old_data['errors']

        old_data['description'] = 'foobar'
        old_data['password'] = 'P4ssw0rd!'

        res = self.app_post_json(url, data=old_data)
        data = json.loads(res.data)

        assert data['status'] == SUCCESS, data

    @with_context
    def test_update_project_json_as_subadmin(self):
        """Test WEB JSON update project as subadmin/non-owner."""
        admin = UserFactory.create()
        owner = UserFactory.create()
        user = UserFactory.create()
        make_subadmin(user)

        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/update?api_key=%s' % (project.short_name, user.api_key)

        res = self.app_get_json(url)
        data = json.loads(res.data)

        assert data['code'] == 403, data

        old_data = dict()

        old_data['description'] = 'foobar'
        old_data['password'] = 'P4ssw0rd!'

        res = self.app_post_json(url, data=old_data)
        data = json.loads(res.data)

        assert data['code'] == 403, data



    @with_context
    def test_05d_get_nonexistant_app_import(self):
        """Test WEB get non existant project import should return 404"""
        self.register()
        # GET
        res = self.app.get('/project/noapp/import', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # POST
        res = self.app.post('/project/noapp/import', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_05d_get_nonexistant_app_task(self):
        """Test WEB get non existant project task should return 404"""
        self.register()
        self.signin()
        res = self.app.get('/project/noapp/task', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Pagination
        res = self.app.get('/project/noapp/task/25', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_05d_get_nonexistant_app_task_json(self):
        """Test WEB get non existant project task should return 404"""
        self.register()
        self.signin()
        res = self.app_get_json('/project/noapp/task')
        assert res.status == '404 NOT FOUND', res.status
        # Pagination
        res = self.app_get_json('/project/noapp/task/25')
        assert res.status == '404 NOT FOUND', res.status


    @with_context
    def test_05d_get_nonexistant_app_results_json(self):
        """Test WEB get non existant project results json should return 404"""
        self.register()
        self.signin()
        res = self.app.get('/project/noapp/24/results.json', follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

    @with_context
    def test_06_applications_without_apps(self):
        """Test WEB projects index without projects works"""
        # Check first without apps
        self.register()
        self.signin()
        self.create_categories()
        res = self.app.get('/project/category/featured', follow_redirects=True)
        assert "Projects" in res.data, res.data
        assert Fixtures.cat_1 not in res.data, res.data

    @with_context
    def test_06_applications_2(self):
        """Test WEB projects index with projects"""
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        project_short_name = project.short_name
        project.published = True
        project.featured = True
        db.session.commit()

        res = self.app.get('/project/category/featured', follow_redirects=True)
        assert self.html_title("Projects") in res.data, res.data
        assert "Projects" in res.data, res.data
        assert project_short_name in res.data, res.data

    @with_context
    def test_06_featured_project_json(self):
        """Test WEB JSON projects index shows featured projects in all the pages works"""
        self.create()
        self.register()
        self.signin()

        project = db.session.query(Project).get(1)
        project.featured = True
        db.session.add(project)
        db.session.commit()
        # Update one task to have more answers than expected
        task = db.session.query(Task).get(1)
        task.n_answers = 1
        db.session.add(task)
        db.session.commit()
        task = db.session.query(Task).get(1)
        cat = db.session.query(Category).get(1)
        url = '/project/category/featured/'
        res = self.app_get_json(url, follow_redirects=True)
        data = json.loads(res.data)
        assert 'pagination' in data.keys(), data
        assert 'active_cat' in data.keys(), data
        assert 'categories' in data.keys(), data
        assert 'projects' in data.keys(), data
        assert data['pagination']['next'] is False, data
        assert data['pagination']['prev'] is False, data
        assert data['pagination']['total'] == 1L, data
        assert data['active_cat']['name'] == 'Featured', data
        assert len(data['projects']) == 1, data
        assert data['projects'][0]['id'] == project.id, data


    @with_context
    def test_06_featured_projects(self):
        """Test WEB projects index shows featured projects in all the pages works"""
        self.create()

        project = db.session.query(Project).get(1)
        project.featured = True
        db.session.add(project)
        db.session.commit()

        self.register()
        self.signin()
        res = self.app.get('/project/category/featured', follow_redirects=True)
        assert self.html_title("Projects") in res.data, res.data
        assert "Projects" in res.data, res.data
        assert '/project/test-app' in res.data, res.data
        assert 'My New Project' in res.data, res.data

        # Update one task to have more answers than expected
        task = db.session.query(Task).get(1)
        task.n_answers = 1
        db.session.add(task)
        db.session.commit()
        task = db.session.query(Task).get(1)
        cat = db.session.query(Category).get(1)
        url = '/project/category/featured/'
        res = self.app.get(url, follow_redirects=True)
        assert 'Featured Projects' in res.data, res.data

    @with_context
    @patch('pybossa.ckan.requests.get')
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_10_get_application(self, Mock, mock2):
        """Test WEB project URL/<short_name> works"""
        # Sign in and create a project
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        Mock.return_value = html_request
        self.register()
        self.signin()
        res = self.new_project()
        project = db.session.query(Project).first()
        project.published = True
        db.session.commit()
        TaskFactory.create(project=project)

        res = self.app.get('/project/sampleapp', follow_redirects=True)
        assert_raises(ValueError, json.loads, res.data)
        msg = "Project: Sample Project"
        assert self.html_title(msg) in res.data, res
        err_msg = "There should be a contribute button"
        assert "Start Contributing Now!" in res.data, err_msg

        res = self.app.get('/project/sampleapp/settings', follow_redirects=True)
        assert_raises(ValueError, json.loads, res.data)
        assert res.status == '200 OK', res.status
        self.signout()

        # Now as an anonymous user
        res = self.app.get('/project/sampleapp', follow_redirects=True)
        assert_raises(ValueError, json.loads, res.data)
        assert "This feature requires being logged in." in res.data, err_msg
        res = self.app.get('/project/sampleapp/settings', follow_redirects=True)
        assert res.status == '200 OK', res.status
        err_msg = "Anonymous user should be redirected to sign in page"
        assert "This feature requires being logged in." in res.data, err_msg

        # Now with a different user
        self.register(fullname="Perico Palotes", name="perico")
        self.signin(email="perico@example.com", password="p4ssw0rd")
        res = self.app.get('/project/sampleapp', follow_redirects=True)
        assert_raises(ValueError, json.loads, res.data)
        print(res.data)
        assert "Sample Project" in res.data, res
        assert "Enter the password to contribute to this project" in res.data, err_msg
        res = self.app.get('/project/sampleapp/settings')
        assert res.status == '403 FORBIDDEN', res.status

    @with_context
    @patch('pybossa.ckan.requests.get')
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_10_get_application_json(self, Mock, mock2):
        """Test WEB project URL/<short_name> works JSON"""
        # Sign in and create a project
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        Mock.return_value = html_request
        self.register()
        self.signin()
        res = self.new_project()
        project = db.session.query(Project).first()
        project.published = True
        db.session.commit()
        TaskFactory.create(project=project)

        res = self.app_get_json('/project/sampleapp/')
        data = json.loads(res.data)
        assert 'last_activity' in data, res.data
        assert 'n_completed_tasks' in data, res.data
        assert 'n_task_runs' in data, res.data
        assert 'n_tasks' in data, res.data
        assert 'n_volunteers' in data, res.data
        assert 'overall_progress' in data, res.data
        assert 'owner' in data, res.data
        assert 'pro_features' in data, res.data
        assert 'project' in data, res.data
        assert 'template' in data, res.data
        assert 'title' in data, res.data
        # private information
        assert 'email_addr' in data['owner'], res.data
        assert 'owner_id' in data['project'], res.data

        res = self.app_get_json('/project/sampleapp/settings')
        assert res.status == '200 OK', res.status
        data = json.loads(res.data)
        assert 'last_activity' in data, res.data
        assert 'n_completed_tasks' in data, res.data
        assert 'n_task_runs' in data, res.data
        assert 'n_tasks' in data, res.data
        assert 'n_volunteers' in data, res.data
        assert 'overall_progress' in data, res.data
        assert 'owner' in data, res.data
        assert 'pro_features' in data, res.data
        assert 'project' in data, res.data
        assert 'template' in data, res.data
        assert 'title' in data, res.data
        # private information
        assert 'api_key' in data['owner'], res.data
        assert 'email_addr' in data['owner'], res.data
        assert 'secret_key' in data['project'], res.data
        assert 'owner_id' in data['project'], res.data

        self.signout()

        # Now as an anonymous user
        '''
        res = self.app_get_json('/project/sampleapp/')
        data = json.loads(res.data)
        assert 'last_activity' in data, res.data
        assert 'n_completed_tasks' in data, res.data
        assert 'n_task_runs' in data, res.data
        assert 'n_tasks' in data, res.data
        assert 'n_volunteers' in data, res.data
        assert 'overall_progress' in data, res.data
        assert 'owner' in data, res.data
        assert 'pro_features' in data, res.data
        assert 'project' in data, res.data
        assert 'template' in data, res.data
        assert 'title' in data, res.data
        # private information
        assert 'api_key' not in data['owner'], res.data
        assert 'email_addr' not in data['owner'], res.data
        assert 'secret_key' not in data['project'], res.data

        res = self.app_get_json('/project/sampleapp/settings')
        assert res.status == '302 FOUND', res.status
        '''

        # Now with a different user
        self.register(fullname="Perico Palotes", name="perico")
        self.signin(email="perico@example.com")
        self.app.post('/project/sampleapp/password', data={
            'password': 'Abc01$'
        });
        res = self.app_get_json('/project/sampleapp/', follow_redirects=True)
        data = json.loads(res.data)
        assert 'last_activity' in data, res.data
        assert 'n_completed_tasks' in data, res.data
        assert 'n_task_runs' in data, res.data
        assert 'n_tasks' in data, res.data
        assert 'n_volunteers' in data, res.data
        assert 'overall_progress' in data, res.data
        assert 'owner' in data, res.data
        assert 'pro_features' in data, res.data
        assert 'project' in data, res.data
        assert 'template' in data, res.data
        assert 'title' in data, res.data
        # private information
        assert 'api_key' not in data['owner'], res.data
        assert 'email_addr' not in data['owner'], res.data
        assert 'secret_key' not in data['project'], res.data

        res = self.app_get_json('/project/sampleapp/settings')
        assert res.status == '403 FORBIDDEN', res.status

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_10b_application_long_description_allows_markdown(self, mock):
        """Test WEB long description markdown is supported"""
        markdown_description = u'Markdown\n======='
        self.register()
        self.signin()
        self.new_project(long_description=markdown_description)

        res = self.app.get('/project/sampleapp', follow_redirects=True)
        data = res.data
        assert '<h1>Markdown</h1>' in data, 'Markdown text not being rendered!'

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_11_create_application(self, mock):
        """Test WEB create a project works"""
        # Create a project as an anonymous user
        res = self.new_project(method="GET")
        assert self.html_title("Sign in") in res.data, res
        assert "This feature requires being logged in." in res.data, res

        res = self.new_project()
        assert self.html_title("Sign in") in res.data, res.data
        assert "This feature requires being logged in." in res.data, res.data

        # Sign in and create a project
        res = self.register()
        res = self.signin()

        res = self.new_project(method="GET")
        assert self.html_title("Create a Project") in res.data, res
        assert "Create the project" in res.data, res

        res = self.new_project(long_description='My Description')
        assert "Sample Project" in res.data
        assert "Project created!" in res.data, res

        project = db.session.query(Project).first()
        assert project.name == 'Sample Project', 'Different names %s' % project.name
        assert project.short_name == 'sampleapp', \
            'Different names %s' % project.short_name

        assert project.long_description == 'My Description', \
            "Long desc should be the same: %s" % project.long_description

        assert project.category is not None, \
            "A project should have a category after being created"

    @with_context
    def test_description_is_generated_only_if_not_provided(self):
        """Test WEB when when creating a project and a description is provided,
        then it is not generated from the long_description"""
        self.register()
        self.signin()
        res = self.new_project(long_description="a" * 300, description='b')

        project = db.session.query(Project).first()
        assert project.description == 'b', project.description

    @with_context
    def test_description_is_generated_from_long_desc(self):
        """Test WEB when creating a project, the description field is
        automatically filled in by truncating the long_description"""
        self.register()
        self.signin()
        res = self.new_project(long_description="Hello", description='')

        project = db.session.query(Project).first()
        assert project.description == "Hello", project.description

    @with_context
    def test_description_is_generated_from_long_desc_formats(self):
        """Test WEB when when creating a project, the description generated
        from the long_description is only text (no html, no markdown)"""
        self.register()
        self.signin()
        res = self.new_project(long_description="## Hello", description='')

        project = db.session.query(Project).first()
        assert '##' not in project.description, project.description
        assert '<h2>' not in project.description, project.description

    @with_context
    def test_description_is_generated_from_long_desc_truncates(self):
        """Test WEB when when creating a project, the description generated
        from the long_description is truncated to 255 chars"""
        self.register()
        self.signin()
        res = self.new_project(long_description="a" * 300, description='')

        project = db.session.query(Project).first()
        assert len(project.description) == 255, len(project.description)
        assert project.description[-3:] == '...'

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_11_a_create_application_errors(self, mock):
        """Test WEB create a project issues the errors"""
        self.register()
        self.signin()
        # Required fields checks
        # Issue the error for the project.name
        res = self.new_project(name="")
        err_msg = "A project must have a name"
        assert "This field is required" in res.data, err_msg

        # Issue the error for the project.short_name
        res = self.new_project(short_name="")
        err_msg = "A project must have a short_name"
        assert "This field is required" in res.data, err_msg

        # Issue the error for the project.description
        res = self.new_project(long_description="")
        err_msg = "A project must have a description"
        assert "This field is required" in res.data, err_msg

        # Issue the error for the project.short_name
        res = self.new_project(short_name='$#/|')
        err_msg = "A project must have a short_name without |/$# chars"
        assert '$#&amp;\/| and space symbols are forbidden' in res.data, err_msg

        # Now Unique checks
        self.new_project()
        res = self.new_project()
        err_msg = "There should be a Unique field"
        assert "Name is already taken" in res.data, err_msg
        assert "Short Name is already taken" in res.data, err_msg

    @with_context
    @patch('pybossa.ckan.requests.get')
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    @patch('pybossa.forms.validator.requests.get')
    def test_12_update_project(self, Mock, mock, mock_webhook):
        """Test WEB update project works"""
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        Mock.return_value = html_request
        mock_webhook.return_value = html_request

        self.register()
        self.signin()
        self.new_project()

        # Get the Update Project web page
        res = self.update_project(method="GET")
        msg = "Project: Sample Project &middot; Update"
        assert self.html_title(msg) in res.data, res
        msg = 'input id="id" name="id" type="hidden" value="1"'
        assert msg in res.data, res
        assert "Save the changes" in res.data, res

        # Check form validation
        res = self.update_project(new_name="",
                                  new_short_name="",
                                  new_description="New description",
                                  new_long_description='New long desc')
        assert "Please correct the errors" in res.data, res.data

        # Update the project
        res = self.update_project(new_name="New Sample Project",
                                  new_short_name="newshortname",
                                  new_description="New description",
                                  new_long_description='New long desc')
        project = db.session.query(Project).first()
        assert "Project updated!" in res.data, res.data
        err_msg = "Project name not updated %s" % project.name
        assert project.name == "New Sample Project", err_msg

        err_msg = "Project description not updated %s" % project.description
        assert project.description == "New description", err_msg

        err_msg = "Project long description not updated %s" % project.long_description
        assert project.long_description == "New long desc", err_msg

    @with_context
    @patch('pybossa.forms.validator.requests.get')
    def test_webhook_to_project(self, mock):
        """Test WEB update sets a webhook for the project"""
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        mock.return_value = html_request

        self.register()
        self.signin()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(owner=owner)

        new_webhook = 'http://mynewserver.com/'

        self.update_project(id=project.id, short_name=project.short_name,
                            new_webhook=new_webhook)

        err_msg = "There should be an updated webhook url."
        assert project.webhook == new_webhook, err_msg

    @with_context
    @patch('pybossa.forms.validator.requests.get')
    def test_webhook_to_project_fails(self, mock):
        """Test WEB update does not set a webhook for the project"""
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=404,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        mock.return_value = html_request

        self.register()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(owner=owner)

        new_webhook = 'http://mynewserver.com/'

        self.update_project(id=project.id, short_name=project.short_name,
                            new_webhook=new_webhook)

        err_msg = "There should not be an updated webhook url."
        assert project.webhook != new_webhook, err_msg

    @with_context
    @patch('pybossa.forms.validator.requests.get')
    def test_webhook_to_project_conn_err(self, mock):
        """Test WEB update does not set a webhook for the project"""
        from requests.exceptions import ConnectionError
        mock.side_effect = ConnectionError

        self.register()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(owner=owner)

        new_webhook = 'http://mynewserver.com/'

        res = self.update_project(id=project.id, short_name=project.short_name,
                                  new_webhook=new_webhook)

        err_msg = "There should not be an updated webhook url."
        assert project.webhook != new_webhook, err_msg

    @with_context
    @patch('pybossa.forms.validator.requests.get')
    def test_add_password_to_project(self, mock_webhook):
        """Test WEB update sets a password for the project"""
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        mock_webhook.return_value = html_request
        self.register()
        self.signin()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(owner=owner)

        self.update_project(id=project.id, short_name=project.short_name,
                            new_protect='true', new_password='Mysecret1@')
        assert project.needs_password(), 'Password not set'


    @with_context
    @patch('pybossa.forms.validator.requests.get')
    def test_remove_password_from_project(self, mock_webhook):
        """Test WEB update removes the password of the project"""
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        mock_webhook.return_value = html_request
        self.register()
        self.signin()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(info={'passwd_hash': 'mysecret'}, owner=owner)

        self.update_project(id=project.id, short_name=project.short_name,
                            new_protect='false', new_password='')

        assert project.needs_password(), 'Password deleted'

    @with_context
    @patch('pybossa.forms.validator.requests.get')
    def test_update_project_errors(self, mock_webhook):
        """Test WEB update form validation issues the errors"""
        self.register()
        self.signin()
        self.new_project()
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')

        mock_webhook.return_value = html_request

        res = self.update_project(new_name="")
        assert "This field is required" in res.data

        res = self.update_project(new_description="")
        assert "You must provide a description." in res.data

        res = self.update_project(new_description="a" * 256)
        assert "Field cannot be longer than 255 characters." in res.data

        res = self.update_project(new_long_description="")
        assert "This field is required" not in res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_14_delete_application(self, mock):
        """Test WEB delete project works"""
        self.register()
        self.signin()
        self.create()
        self.new_project()
        res = self.delete_project(method="GET")
        msg = "Project: Sample Project &middot; Delete"
        assert self.html_title(msg) in res.data, res
        assert "No, do not delete it" in res.data, res

        project = db.session.query(Project).filter_by(short_name='sampleapp').first()
        res = self.delete_project(method="GET")
        msg = "Project: Sample Project &middot; Delete"
        assert self.html_title(msg) in res.data, res
        assert "No, do not delete it" in res.data, res

        res = self.delete_project()
        assert "Project deleted!" in res.data, res

        self.signin(email=Fixtures.email_addr2, password=Fixtures.password)
        res = self.delete_project(short_name=Fixtures.project_short_name)
        assert res.status_code == 403, res.status_code

    @with_context
    @patch('pybossa.repositories.project_repository.uploader')
    def test_delete_project_deletes_task_zip_files_too(self, uploader):
        """Test WEB delete project also deletes zip files for task and taskruns"""
        Fixtures.create()
        make_subadmin_by(email_addr=u'tester@tester.com')
        self.signin(email=u'tester@tester.com', password=u'tester')
        res = self.app.post('/project/test-app/delete', follow_redirects=True)
        expected = [call('1_test-app_task_json.zip', 'user_2'),
                    call('1_test-app_task_csv.zip', 'user_2'),
                    call('1_test-app_task_run_json.zip', 'user_2'),
                    call('1_test-app_task_run_csv.zip', 'user_2')]
        assert uploader.delete_file.call_args_list == expected

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_16_task_status_completed(self, mock):
        """Test WEB Task Status Completed works"""
        self.register()
        self.signin()
        self.new_project()

        project = db.session.query(Project).first()
        # We use a string here to check that it works too
        project.published = True
        task = Task(project_id=project.id, n_answers=10)
        db.session.add(task)
        db.session.commit()

        res = self.app.get('project/%s/tasks/browse' % (project.short_name),
                           follow_redirects=True)
        dom = BeautifulSoup(res.data)
        assert "Sample Project" in res.data, res.data
        assert re.search('0\s+of\s+10', res.data), res.data
        err_msg = "Download button should be disabled"
        assert dom.find(id='nothingtodownload') is not None, err_msg

        for i in range(5):
            task_run = TaskRun(project_id=project.id, task_id=1,
                               info={'answer': 1})
            db.session.add(task_run)
            db.session.commit()
            self.app.get('api/project/%s/newtask' % project.id)

        res = self.app.get('project/%s/tasks/browse' % (project.short_name),
                           follow_redirects=True)
        dom = BeautifulSoup(res.data)
        assert "Sample Project" in res.data, res.data
        assert re.search('5\s+of\s+10', res.data), res.data
        err_msg = "Download Partial results button should be shown"
        assert dom.find(id='partialdownload') is not None, err_msg

        for i in range(5):
            task_run = TaskRun(project_id=project.id, task_id=1,
                               info={'answer': 1})
            db.session.add(task_run)
            db.session.commit()
            self.app.get('api/project/%s/newtask' % project.id)

        project = db.session.query(Project).first()

        res = self.app.get('project/%s/tasks/browse' % (project.short_name),
                           follow_redirects=True)
        assert "Sample Project" in res.data, res.data
        msg = '<a class="label label-success" target="_blank" href="/project/sampleapp/task/1">#1</a>'
        assert msg in res.data, res.data
        assert re.search('10\s+of\s+10', res.data), res.data
        dom = BeautifulSoup(res.data)
        err_msg = "Download Full results button should be shown"
        assert dom.find(id='fulldownload') is not None, err_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_17_export_task_runs(self, mock):
        """Test WEB TaskRun export works"""
        self.register()
        self.signin()
        self.new_project()

        project = db.session.query(Project).first()
        task = Task(project_id=project.id, n_answers=10)
        db.session.add(task)
        db.session.commit()

        for i in range(10):
            task_run = TaskRun(project_id=project.id, task_id=1, info={'answer': 1})
            db.session.add(task_run)
            db.session.commit()

        project = db.session.query(Project).first()
        res = self.app.get('project/%s/%s/results.json' % (project.short_name, 1),
                           follow_redirects=True)
        data = json.loads(res.data)
        data = data['taskruns_info']
        assert len(data) == 10, data
        for tr in data:
            assert tr['info']['answer'] == 1, tr

        # Check with correct project but wrong task id
        res = self.app.get('project/%s/%s/results.json' % (project.short_name, 5000),
                           follow_redirects=True)
        assert res.status_code == 404, res.status_code

    @with_context
    @patch('pybossa.view.projects._get_locks', return_value={2: 100})
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_export_task_run_statuses(self, upload, locks):
        """Test WEB TaskRun statuses export works"""
        self.register()
        self.signin()
        self.new_project()

        UserFactory.create(id=2)

        project = db.session.query(Project).first()
        task = Task(project_id=project.id, n_answers=2)
        db.session.add(task)
        db.session.commit()

        task_run = TaskRun(project_id=project.id,
                           task_id=1,
                           info={'answer': 1},
                           user_id=1)
        db.session.add(task_run)
        db.session.commit()

        project = db.session.query(Project).first()
        res = self.app.get(
                'project/{}/{}/result_status'.format(
                    project.short_name, 1),
                follow_redirects=True)
        data = json.loads(res.data)
        assert len(data['user_details']) == 2, data
        assert data['redundancy'] == 2, data

        for user_detail in data['user_details']:
            if user_detail['status'] == 'Completed':
                completed = user_detail
            if user_detail['status'] == 'Locked':
                locked = user_detail

        assert not completed['lock_ttl'], data
        assert locked['lock_ttl'], data

        # Check with correct project but wrong task id
        res = self.app.get(
                'project/{}/{}/result_status'.format(
                    project.short_name, 5000),
                follow_redirects=True)
        assert res.status_code == 404, res.status_code

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_18_task_status_wip(self, mock):
        """Test WEB Task Status on going works"""
        self.register()
        self.signin()
        self.new_project()

        project = db.session.query(Project).first()
        project.published = True
        task = Task(project_id=project.id, n_answers=10)
        db.session.add(task)
        db.session.commit()

        project = db.session.query(Project).first()

        res = self.app.get('project/%s/tasks/browse' % (project.short_name),
                           follow_redirects=True)
        assert "Sample Project" in res.data, res.data
        msg = '<a class="label label-info" target="_blank" href="/project/sampleapp/task/1">#1</a>'
        assert msg in res.data, res.data
        assert re.search('0\s+of\s+10', res.data), res.data

        # For a non existing page
        res = self.app.get('project/%s/tasks/browse/5000' % (project.short_name),
                           follow_redirects=True)
        assert 'Displaying 0  of 1' in res.data, res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_18_task_status_wip_json(self, mock):
        """Test WEB Task Status on going works"""
        self.register()
        self.signin()
        self.new_project()

        project = db.session.query(Project).first()
        project.published = True
        task = Task(project_id=project.id, n_answers=10)
        db.session.add(task)
        db.session.commit()

        project = db.session.query(Project).first()

        res = self.app_get_json('project/%s/tasks/browse' % (project.short_name))
        print(res.data)
        data = json.loads(res.data)
        err_msg = 'key missing'
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pagination' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'tasks' in data, err_msg
        assert 'template' in data, err_msg
        assert 'title' in data, err_msg

        assert "Sample Project" in data['title'], data
        assert data['tasks'][0]['n_answers'] == 10, data

        ## new browse task filtering
        # For a non existing page
        #res = self.app_get_json('project/%s/tasks/browse/5000' % (project.short_name))
        #assert res.status_code == 404, res.status_code

    @with_context
    def test_19_app_index_categories(self):
        """Test WEB Project Index categories works"""
        self.register()
        self.signin()
        self.create()

        res = self.app.get('project/category/featured', follow_redirects=True)
        assert "Projects" in res.data, res.data
        assert Fixtures.cat_1 in res.data, res.data

        task = db.session.query(Task).get(1)
        # Update one task to have more answers than expected
        task.n_answers = 1
        db.session.add(task)
        db.session.commit()
        task = db.session.query(Task).get(1)
        cat = db.session.query(Category).get(1)
        url = '/project/category/%s/' % Fixtures.cat_1
        res = self.app.get(url, follow_redirects=True)
        tmp = '%s Projects' % Fixtures.cat_1
        assert tmp in res.data, res

    @with_context
    def test_app_index_categories_pagination(self):
        """Test WEB Project Index categories pagination works"""
        from flask import current_app
        n_apps = current_app.config.get('APPS_PER_PAGE')
        current_app.config['APPS_PER_PAGE'] = 1
        category = CategoryFactory.create(name='category', short_name='cat')
        for project in ProjectFactory.create_batch(2, category=category):
            TaskFactory.create(project=project)
        admin_user = UserFactory.create(admin=True)
        admin_user.set_password('1234')
        self.signin(email=admin_user.email_addr, password='1234')
        page1 = self.app.get('/project/category/%s/' % category.short_name)
        page2 = self.app.get('/project/category/%s/page/2/' % category.short_name)
        current_app.config['APPS_PER_PAGE'] = n_apps

        assert '<a href="/project/category/cat/page/2/" rel="nofollow">2</a>' in page1.data
        assert page2.status_code == 200, page2.status_code
        assert '<a href="/project/category/cat/" rel="nofollow">1</a>' in page2.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_20_app_index_published(self, mock):
        """Test WEB Project Index published works"""
        self.register()
        self.signin()
        self.new_project()
        self.update_project(new_category_id="1")
        project = db.session.query(Project).first()
        project.published = True
        project.featured = True
        db.session.commit()
        #self.signout()

        res = self.app.get('project/category/featured', follow_redirects=True)
        assert "Featured Projects" in res.data, res.data
        assert "Sample Project" in res.data, res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_20_json_project_index_draft(self, mock):
        """Test WEB JSON Project Index draft works"""
        # Create root
        self.register()
        self.signin()
        self.new_project()
        self.signout()
        # Create a user
        self.register(fullname="jane", name="jane", email="jane@jane.com")
        self.signout()

        # As Anonymous
        res = self.app_get_json('/project/category/draft/', follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "Anonymous should not see draft apps"
        assert dom.find(id='signin') is not None, err_msg

        # As authenticated but not admin
        self.signin(email="jane@jane.com", password="p4ssw0rd")
        res = self.app_get_json('/project/category/draft/', follow_redirects=True)
        data = json.loads(res.data)
        assert res.status_code == 403, "Non-admin should not see draft apps"
        assert data.get('code') == 403, data
        self.signout()

        # As Admin
        self.signin()
        res = self.app_get_json('/project/category/draft/')
        data = json.loads(res.data)
        project = project_repo.get(1)
        assert 'pagination' in data.keys(), data
        assert 'active_cat' in data.keys(), data
        assert 'categories' in data.keys(), data
        assert 'projects' in data.keys(), data
        assert data['pagination']['next'] is False, data
        assert data['pagination']['prev'] is False, data
        assert data['pagination']['total'] == 1L, data
        assert data['active_cat']['name'] == 'Draft', data
        assert len(data['projects']) == 1, data
        assert data['projects'][0]['id'] == project.id, data


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_20_app_index_draft(self, mock):
        """Test WEB Project Index draft works"""
        # Create root
        self.register()
        self.signin()
        self.new_project()
        self.signout()
        # Create a user
        self.register(fullname="jane", name="jane", email="jane@jane.com")
        self.signin(email="jane@jane.com", password="p4ssw0rd")
        self.signout()

        # As Anonymous
        res = self.app.get('/project/category/draft', follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "Anonymous should not see draft apps"
        assert dom.find(id='signin') is not None, err_msg

        # As authenticated but not admin
        self.signin(email="jane@jane.com", password="p4ssw0rd")
        res = self.app.get('/project/category/draft', follow_redirects=True)
        assert res.status_code == 403, "Non-admin should not see draft apps"
        self.signout()

        # As Admin
        self.signin()
        res = self.app.get('/project/category/draft', follow_redirects=True)
        assert "project-published" not in res.data, res.data
        assert "draft" in res.data, res.data
        assert "Sample Project" in res.data, res.data
        assert 'Draft Projects' in res.data, res.data

    @with_context
    def test_21_get_specific_ongoing_task_anonymous(self):
        """Test WEB get specific ongoing task_id for
        a project works as anonymous"""
        self.create()
        self.delete_task_runs()
        project = db.session.query(Project).first()
        task = db.session.query(Task)\
                 .filter(Project.id == project.id)\
                 .first()
        res = self.app.get('project/%s/task/%s' % (project.short_name, task.id),
                           follow_redirects=True)
        #assert 'TaskPresenter' in res.data, res.data
        #msg = "?next=%2Fproject%2F" + project.short_name + "%2Ftask%2F" + str(task.id)
        #assert msg in res.data, res.data

        # Try with only registered users
        project.allow_anonymous_contributors = False
        db.session.add(project)
        db.session.commit()
        res = self.app.get('project/%s/task/%s' % (project.short_name, task.id),
                           follow_redirects=True)
        assert 'This feature requires being logged in' in res.data

    @with_context
    def test_21_get_specific_ongoing_task_anonymous_json(self):
        """Test WEB get specific ongoing task_id for
        a project works as anonymous"""
        self.create()
        self.delete_task_runs()
        project = db.session.query(Project).first()
        task = db.session.query(Task)\
                 .filter(Project.id == project.id)\
                 .first()
        res = self.app_get_json('project/%s/task/%s' % (project.short_name, task.id))
        #data = json.loads(res.data)
        #err_msg = 'field missing'
        #assert 'flash' in data, err_msg
        #assert 'owner' in data, err_msg
        #assert 'project' in data, err_msg
        #assert 'status' in data, err_msg
        #assert 'template' in data, err_msg
        #assert 'title' in data, err_msg
        #err_msg = 'wrong field value'
        #assert data['status'] == 'warning', err_msg
        #assert data['template'] == '/projects/presenter.html', err_msg
        #assert 'Contribute' in data['title'], err_msg
        #err_msg = 'private field data exposed'
        #assert 'api_key' not in data['owner'], err_msg
        #assert 'email_addr' not in data['owner'], err_msg
        #assert 'secret_key' not in data['project'], err_msg

        # Try with only registered users
        project.allow_anonymous_contributors = False
        db.session.add(project)
        db.session.commit()
        res = self.app_get_json('project/%s/task/%s' % (project.short_name, task.id))
        assert res.status_code == 302

    @with_context
    def test_23_get_specific_ongoing_task_user(self):
        """Test WEB get specific ongoing task_id for a project works as an user"""
        self.create()
        self.delete_task_runs()
        self.register()
        self.signin()
        make_subadmin_by(email_addr='johndoe@example.com')
        project = db.session.query(Project).first()
        task = db.session.query(Task).filter(Project.id == project.id).first()
        res = self.app.get('project/%s/task/%s' % (project.short_name, task.id),
                           follow_redirects=True)
        assert 'TaskPresenter' in res.data, res.data

    @with_context
    def test_23_get_specific_ongoing_task_user_json(self):
        """Test WEB get specific ongoing task_id for a project works as an user"""
        self.create()
        self.delete_task_runs()
        self.register()
        make_subadmin_by(email_addr='johndoe@example.com')
        self.signin()
        project = db.session.query(Project).first()
        task = db.session.query(Task).filter(Project.id == project.id).first()
        res = self.app_get_json('project/%s/task/%s' % (project.short_name, task.id))
        data = json.loads(res.data)
        err_msg = 'field missing'
        assert 'owner' in data, err_msg
        assert 'project' in data, err_msg
        assert 'template' in data, err_msg
        assert 'title' in data, err_msg
        err_msg = 'wrong field value'
        assert data['template'] == '/projects/presenter.html', err_msg
        assert 'Contribute' in data['title'], err_msg
        err_msg = 'private field data exposed'
        assert 'api_key' not in data['owner'], err_msg
        assert 'email_addr' not in data['owner'], err_msg
        assert 'secret_key' not in data['project'], err_msg
        err_msg = 'this field should not existing'
        assert 'flash' not in data, err_msg
        assert 'status' not in data, err_msg

    @with_context
    @patch('pybossa.view.projects.ContributionsGuard')
    def test_get_specific_ongoing_task_marks_task_as_requested(self, guard):
        fake_guard_instance = mock_contributions_guard()
        guard.return_value = fake_guard_instance
        self.create()
        user = user_repo.get(1)
        self.signin_user(user)
        project = db.session.query(Project).first()
        task = db.session.query(Task).filter(Project.id == project.id).first()
        res = self.app.get('project/%s/task/%s' % (project.short_name, task.id),
                           follow_redirects=True)

        assert fake_guard_instance.stamp.called

    @with_context
    @patch('pybossa.view.projects.ContributionsGuard')
    def test_get_specific_ongoing_task_marks_task_as_requested_json(self, guard):
        fake_guard_instance = mock_contributions_guard()
        guard.return_value = fake_guard_instance
        self.create()
        self.register()
        make_subadmin_by(email_addr='johndoe@example.com')
        self.signin()
        project = db.session.query(Project).first()
        task = db.session.query(Task).filter(Project.id == project.id).first()
        res = self.app_get_json('project/%s/task/%s' % (project.short_name, task.id))
        print(res.data)

        assert fake_guard_instance.stamp.called


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_25_get_wrong_task_app(self, mock):
        """Test WEB get wrong task.id for a project works"""
        self.register()
        self.signin()
        self.create()
        project1 = db.session.query(Project).get(1)
        project1_short_name = project1.short_name

        db.session.query(Task).filter(Task.project_id == 1).first()

        self.register()
        self.signin()
        self.new_project()
        app2 = db.session.query(Project).get(2)
        self.new_task(app2.id)
        task2 = db.session.query(Task).filter(Task.project_id == 2).first()
        task2_id = task2.id

        res = self.app.get('/project/%s/task/%s' % (project1_short_name, task2_id))
        assert "Error" in res.data, res.data
        msg = "This task does not belong to %s" % project1_short_name
        assert msg in res.data, res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_25_get_wrong_task_app_json(self, mock):
        """Test WEB get wrong task.id for a project works"""
        self.create()
        project1 = db.session.query(Project).get(1)
        project1_short_name = project1.short_name

        db.session.query(Task).filter(Task.project_id == 1).first()

        self.register()
        make_subadmin_by(email_addr='johndoe@example.com')
        self.signin()
        self.new_project()
        app2 = db.session.query(Project).get(2)
        self.new_task(app2.id)
        task2 = db.session.query(Task).filter(Task.project_id == 2).first()
        task2_id = task2.id

        res = self.app_get_json('/project/%s/task/%s' % (project1_short_name, task2_id))
        data = json.loads(res.data)
        err_msg = 'expected field is missing'
        assert 'owner' in data, err_msg
        assert 'project' in data, err_msg
        assert 'template' in data, err_msg
        assert 'title' in data, err_msg
        err_msg = 'wrong field value'
        assert data['template'] == '/projects/task/wrong.html', err_msg
        assert 'Contribute' in data['title'], err_msg
        err_msg = 'private field data exposed'
        assert 'api_key' not in data['owner'], err_msg
        assert 'email_addr' not in data['owner'], err_msg
        assert 'secret_key' not in data['project'], err_msg

    @with_context
    def test_26_tutorial_signed_user(self):
        """Test WEB tutorials work as signed in user"""
        self.create()
        project1 = db.session.query(Project).get(1)
        project1.info = dict(tutorial="some help", task_presenter="presenter")
        db.session.commit()
        self.register()
        self.signin()
        # First time accessing the project should redirect me to the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        err_msg = "There should be some tutorial for the project"
        assert "some help" in res.data, err_msg
        # Second time should give me a task, and not the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        assert "some help" not in res.data

        # Check if the tutorial can be accessed directly
        res = self.app.get('/project/test-app/tutorial', follow_redirects=True)
        err_msg = "There should be some tutorial for the project"
        assert "some help" in res.data, err_msg

    @with_context
    def test_26_tutorial_signed_user_json(self):
        """Test WEB tutorials work as signed in user"""
        self.create()
        project1 = db.session.query(Project).get(1)
        project1.info = dict(tutorial="some help", task_presenter="presenter")
        db.session.commit()
        self.register()
        self.signin()
        # First time accessing the project should redirect me to the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        err_msg = "There should be some tutorial for the project"
        assert "some help" in res.data, err_msg
        # Second time should give me a task, and not the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        assert "some help" not in res.data

        # Check if the tutorial can be accessed directly
        res = self.app_get_json('/project/test-app/tutorial')
        data = json.loads(res.data)
        err_msg = 'key missing'
        assert 'owner' in data, err_msg
        assert 'project' in data, err_msg
        assert 'template' in data, err_msg
        assert 'title' in data, err_msg
        err_msg = 'project tutorial missing'
        assert 'My New Project' in data['title'], err_msg

    @nottest
    @with_context
    def test_27_tutorial_anonymous_user(self):
        """Test WEB tutorials work as an anonymous user"""
        self.create()
        project = db.session.query(Project).get(1)
        project.info = dict(tutorial="some help", task_presenter="presenter")
        db.session.commit()
        self.register()
        # First time accessing the project should redirect me to the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        err_msg = "There should be some tutorial for the project"
        assert "some help" in res.data, err_msg
        # Second time should give me a task, and not the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        assert "some help" not in res.data

        # Check if the tutorial can be accessed directly
        res = self.app.get('/project/test-app/tutorial', follow_redirects=True)
        err_msg = "There should be some tutorial for the project"
        assert "some help" in res.data, err_msg

    @nottest
    @with_context
    def test_27_tutorial_anonymous_user_json(self):
        """Test WEB tutorials work as an anonymous user"""
        self.create()
        project = db.session.query(Project).get(1)
        project.info = dict(tutorial="some help", task_presenter="presenter")
        db.session.commit()
        # First time accessing the project should redirect me to the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        err_msg = "There should be some tutorial for the project"
        assert "some help" in res.data, err_msg
        # Second time should give me a task, and not the tutorial
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        assert "some help" not in res.data

        # Check if the tutorial can be accessed directly
        res = self.app_get_json('/project/test-app/tutorial')
        data = json.loads(res.data)
        err_msg = 'key missing'
        assert 'owner' in data, err_msg
        assert 'project' in data, err_msg
        assert 'template' in data, err_msg
        assert 'title' in data, err_msg
        err_msg = 'project tutorial missing'
        assert 'My New Project' in data['title'], err_msg

    @with_context
    def test_28_non_tutorial_signed_user(self):
        """Test WEB project without tutorial work as signed in user"""
        self.create()
        project = db.session.query(Project).get(1)
        project.info = dict(task_presenter="the real presenter")
        db.session.commit()
        self.register()
        self.signin()
        # First time accessing the project should show the presenter
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        err_msg = "There should be a presenter for the project"
        assert "the real presenter" in res.data, err_msg
        # Second time accessing the project should show the presenter
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        assert "the real presenter" in res.data, err_msg

    @with_context
    def test_29_non_tutorial_anonymous_user(self):
        """Test WEB project without tutorials work as an anonymous user."""
        '''
        self.create()
        project = db.session.query(Project).get(1)
        project.info = dict(task_presenter="the real presenter")
        db.session.commit()
        # First time accessing the project should show the presenter
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        err_msg = "There should be a presenter for the project"
        assert "the real presenter" in res.data, err_msg
        # Second time accessing the project should show the presenter
        res = self.app.get('/project/test-app/newtask', follow_redirects=True)
        assert "the real presenter" in res.data, err_msg
        '''

    @with_context
    def test_message_is_flashed_contributing_to_project_without_presenter(self):
        project = ProjectFactory.create(info={})
        task = TaskFactory.create(project=project)
        newtask_url = '/project/%s/newtask' % project.short_name
        task_url = '/project/%s/task/%s' % (project.short_name, task.id)
        message = ("Sorry, but this project is still a draft and does "
                   "not have a task presenter.")

        newtask_response = self.app.get(newtask_url, follow_redirects=True)
        task_response = self.app.get(task_url, follow_redirects=True)

        assert message in newtask_response.data
        assert message in task_response.data

    @with_context
    def test_message_is_flashed_contributing_to_project_without_presenter(self):
        """Test task_presenter check is not raised."""
        project = ProjectFactory.create(info={})
        task = TaskFactory.create(project=project)
        newtask_url = '/project/%s/newtask' % project.short_name
        task_url = '/project/%s/task/%s' % (project.short_name, task.id)
        message = ("Sorry, but this project is still a draft and does "
                   "not have a task presenter.")
        with patch.dict(self.flask_app.config,
                        {'DISABLE_TASK_PRESENTER': True}):
            newtask_response = self.app.get(newtask_url)
            task_response = self.app.get(task_url, follow_redirects=True)

            assert message not in newtask_response.data, newtask_response.data
            assert message not in task_response.data, task_response.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_30_app_id_owner(self, mock):
        """Test WEB project settings page shows the ID to the owner"""
        self.register()
        self.signin()
        self.new_project()

        res = self.app.get('/project/sampleapp/settings', follow_redirects=True)
        assert "Sample Project" in res.data, ("Project should be shown to "
                                              "the owner")
        # TODO: Needs discussion. Disable for now.
        # msg = '<strong><i class="icon-cog"></i> ID</strong>: 1'
        # err_msg = "Project ID should be shown to the owner"
        # assert msg in res.data, err_msg

        self.signout()
        self.create()
        self.signin(email=Fixtures.email_addr2, password=Fixtures.password)
        res = self.app.get('/project/sampleapp/settings', follow_redirects=True)
        assert res.status_code == 403, res.status_code

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    @patch('pybossa.ckan.requests.get')
    def test_30_app_id_anonymous_user(self, Mock, mock):
        """Test WEB project page does not show the ID to anonymous users"""
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        Mock.return_value = html_request

        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        project.published = True
        db.session.commit()
        self.signout()

        res = self.app.get('/project/sampleapp', follow_redirects=True)
        assert '<strong><i class="icon-cog"></i> ID</strong>: 1' not in \
            res.data, "Project ID should be shown to the owner"

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_31_user_profile_progress(self, mock):
        """Test WEB user progress profile page works"""
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        task = Task(project_id=project.id, n_answers=10)
        db.session.add(task)
        task_run = TaskRun(project_id=project.id, task_id=1, user_id=1,
                           info={'answer': 1})
        db.session.add(task_run)
        db.session.commit()

        res = self.app.get('account/johndoe', follow_redirects=True)
        assert "Sample Project" in res.data

    @with_context
    def test_32_oauth_password(self):
        """Test WEB user sign in without password works"""
        user = User(email_addr="johndoe@johndoe.com",
                    name="John Doe",
                    passwd_hash=None,
                    fullname="johndoe",
                    api_key="api-key")
        db.session.add(user)
        db.session.commit()
        res = self.signin()
        assert "Ooops, we didn&#39;t find you in the system" in res.data, res.data

    @with_context
    def test_39_google_oauth_creation(self):
        """Test WEB Google OAuth creation of user works"""
        fake_response = {
            u'access_token': u'access_token',
            u'token_type': u'Bearer',
            u'expires_in': 3600,
            u'id_token': u'token'}

        fake_user = {
            u'family_name': u'Doe', u'name': u'John Doe',
            u'picture': u'https://goo.gl/img.jpg',
            u'locale': u'en',
            u'gender': u'male',
            u'email': u'john@gmail.com',
            u'birthday': u'0000-01-15',
            u'link': u'https://plus.google.com/id',
            u'given_name': u'John',
            u'id': u'111111111111111111111',
            u'verified_email': True}

        from pybossa.view import google
        response_user = google.manage_user(fake_response['access_token'],
                                           fake_user)

        user = db.session.query(User).get(1)

        assert user.email_addr == response_user.email_addr, response_user

    @with_context
    def test_40_google_oauth_creation(self):
        """Test WEB Google OAuth detects same user name/email works"""
        fake_response = {
            u'access_token': u'access_token',
            u'token_type': u'Bearer',
            u'expires_in': 3600,
            u'id_token': u'token'}

        fake_user = {
            u'family_name': u'Doe', u'name': u'John Doe',
            u'picture': u'https://goo.gl/img.jpg',
            u'locale': u'en',
            u'gender': u'male',
            u'email': u'john@gmail.com',
            u'birthday': u'0000-01-15',
            u'link': u'https://plus.google.com/id',
            u'given_name': u'John',
            u'id': u'111111111111111111111',
            u'verified_email': True}

        self.register()
        self.signout()

        from pybossa.view import google
        response_user = google.manage_user(fake_response['access_token'],
                                           fake_user)

        assert response_user is None, response_user

    @with_context
    def test_39_facebook_oauth_creation(self):
        """Test WEB Facebook OAuth creation of user works"""
        fake_response = {
            u'access_token': u'access_token',
            u'token_type': u'Bearer',
            u'expires_in': 3600,
            u'id_token': u'token'}

        fake_user = {
            u'username': u'teleyinex',
            u'first_name': u'John',
            u'last_name': u'Doe',
            u'verified': True,
            u'name': u'John Doe',
            u'locale': u'en_US',
            u'gender': u'male',
            u'email': u'johndoe@example.com',
            u'quotes': u'"quote',
            u'link': u'http://www.facebook.com/johndoe',
            u'timezone': 1,
            u'updated_time': u'2011-11-11T12:33:52+0000',
            u'id': u'11111'}

        from pybossa.view import facebook
        response_user = facebook.manage_user(fake_response['access_token'],
                                             fake_user)

        user = db.session.query(User).get(1)

        assert user.email_addr == response_user.email_addr, response_user

    @with_context
    def test_40_facebook_oauth_creation(self):
        """Test WEB Facebook OAuth detects same user name/email works"""
        fake_response = {
            u'access_token': u'access_token',
            u'token_type': u'Bearer',
            u'expires_in': 3600,
            u'id_token': u'token'}

        fake_user = {
            u'username': u'teleyinex',
            u'first_name': u'John',
            u'last_name': u'Doe',
            u'verified': True,
            u'name': u'John Doe',
            u'locale': u'en_US',
            u'gender': u'male',
            u'email': u'johndoe@example.com',
            u'quotes': u'"quote',
            u'link': u'http://www.facebook.com/johndoe',
            u'timezone': 1,
            u'updated_time': u'2011-11-11T12:33:52+0000',
            u'id': u'11111'}

        self.register()
        self.signout()

        from pybossa.view import facebook
        response_user = facebook.manage_user(fake_response['access_token'],
                                             fake_user)

        assert response_user is None, response_user

    @with_context
    def test_39_twitter_oauth_creation(self):
        """Test WEB Twitter OAuth creation of user works"""
        fake_response = {
            u'access_token': {u'oauth_token': u'oauth_token',
                              u'oauth_token_secret': u'oauth_token_secret'},
            u'token_type': u'Bearer',
            u'expires_in': 3600,
            u'id_token': u'token'}

        fake_user = {u'screen_name': u'johndoe',
                     u'user_id': u'11111'}

        from pybossa.view import twitter
        response_user = twitter.manage_user(fake_response['access_token'],
                                            fake_user)

        user = db.session.query(User).get(1)

        assert user.email_addr == response_user.email_addr, response_user

        res = self.signin(email=user.email_addr, password='wrong')
        msg = "It seems like you signed up with your Twitter account"
        assert msg in res.data, msg

    @with_context
    def test_40_twitter_oauth_creation(self):
        """Test WEB Twitter OAuth detects same user name/email works"""
        fake_response = {
            u'access_token': {u'oauth_token': u'oauth_token',
                              u'oauth_token_secret': u'oauth_token_secret'},
            u'token_type': u'Bearer',
            u'expires_in': 3600,
            u'id_token': u'token'}

        fake_user = {u'screen_name': u'johndoe',
                     u'user_id': u'11111'}

        self.register()
        self.signout()

        from pybossa.view import twitter
        response_user = twitter.manage_user(fake_response['access_token'],
                                            fake_user)

        assert response_user is None, response_user

    @with_context
    def test_41_password_change_json(self):
        """Test WEB password JSON changing"""
        password = "mehpassword"
        self.register(password=password)
        self.signin(password=password)
        url = '/account/johndoe/update'
        csrf = self.get_csrf(url)
        payload = {'current_password': password,
                   'new_password': "p4ssw0rd",
                   'confirm': "p4ssw0rd",
                   'btn': 'Password'}
        res = self.app.post(url,
                            data=json.dumps(payload),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})
        data = json.loads(res.data)
        assert "Yay, you changed your password succesfully!" == data.get('flash'), res.data
        assert data.get('status') == SUCCESS, data

        password = "p4ssw0rd"
        self.signin(password=password)
        payload['current_password'] = "wrongpasswor"
        res = self.app.post(url,
                            data=json.dumps(payload),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})
        msg = "Your current password doesn't match the one in our records"
        data = json.loads(res.data)
        assert msg == data.get('flash'), data
        assert data.get('status') == ERROR, data

        res = self.app.post('/account/johndoe/update',
                            data=json.dumps({'current_password': '',
                                  'new_password': '',
                                  'confirm': '',
                                  'btn': 'Password'}),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})
        data = json.loads(res.data)
        msg = "Please correct the errors"
        err_msg = "There should be a flash message"
        assert data.get('flash') == msg, (err_msg, data)
        assert data.get('status') == ERROR, (err_msg, data)

    @with_context
    def test_42_avatar_change_json(self):
        """Test WEB avatar JSON changing"""
        import io
        self.register()
        self.signin()
        user = user_repo.get_by(name='johndoe')
        print(user)
        url = '/account/johndoe/update'
        csrf = self.get_csrf(url)
        payload = {'avatar': (io.BytesIO(b"abcdef"), 'test.jpg'),
                   'id': user.id,
                   'x1': "100",
                   'x2': '100',
                   'y1': '300',
                   'y2': '300',
                   'btn': 'Upload'}
        res = self.app.post(url,
                            data=payload,
                            follow_redirects=True,
                            content_type="multipart/form-data",
                            headers={'X-CSRFToken': csrf})
        err_msg = "Avatar should be updated"
        assert "Your avatar has been updated!" in res.data, (res.data, err_msg)

        payload['avatar'] = None
        res = self.app.post(url,
                            data=payload,
                            follow_redirects=True,
                            content_type="multipart/form-data",
                            headers={'X-CSRFToken': csrf})
        msg = "You have to provide an image file to update your avatar"
        assert msg in res.data, (res.data, msg)

    @with_context
    def test_41_password_change(self):
        """Test WEB password changing"""
        password = "mehpassword"
        self.register(password=password)
        self.signin(password=password)
        res = self.app.post('/account/johndoe/update',
                            data={'current_password': password,
                                  'new_password': "p4ssw0rd",
                                  'confirm': "p4ssw0rd",
                                  'btn': 'Password'},
                            follow_redirects=True)
        assert "Yay, you changed your password succesfully!" in res.data, res.data

        password = "p4ssw0rd"
        self.signin(password=password)
        res = self.app.post('/account/johndoe/update',
                            data={'current_password': "wrongpassword",
                                  'new_password': "p4ssw0rd",
                                  'confirm': "p4ssw0rd",
                                  'btn': 'Password'},
                            follow_redirects=True)
        msg = "Your current password doesn&#39;t match the one in our records"
        assert msg in res.data

        res = self.app.post('/account/johndoe/update',
                            data={'current_password': '',
                                  'new_password': '',
                                  'confirm': '',
                                  'btn': 'Password'},
                            follow_redirects=True)
        msg = "Please correct the errors"
        assert msg in res.data

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account(self, mock):
        """Test WEB delete account works"""
        from pybossa.jobs import delete_account
        self.register()
        self.signin()
        admin = user_repo.get(1)
        user = UserFactory.create(id=100)
        res = self.app.get('/account/%s/delete' % user.name)
        assert res.status_code == 302, res.status_code
        assert '/admin' in res.data
        mock.assert_called_with(delete_account, user.id, admin.email_addr)

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account_anon(self, mock):
        """Test WEB delete account anon fails"""
        from pybossa.jobs import delete_account
        self.register()
        self.signout()
        res = self.app.get('/account/johndoe/delete')
        assert res.status_code == 302, res.status_code
        assert 'account/signin?next' in res.data

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account_json_anon(self, mock):
        """Test WEB delete account json anon fails"""
        from pybossa.jobs import delete_account
        self.register()
        self.signout()
        res = self.app_get_json('/account/johndoe/delete')
        assert res.status_code == 302, res.status_code
        assert 'account/signin?next' in res.data

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account_other_user(self, mock):
        """Test WEB delete account other user fails"""
        from pybossa.jobs import delete_account
        user = UserFactory.create(id=5000)
        self.register()
        self.signin()
        res = self.app.get('/account/%s/delete' % user.name)
        assert res.status_code == 403, res.status_code

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account_json_other_user(self, mock):
        """Test WEB delete account json anon fails"""
        from pybossa.jobs import delete_account
        user = UserFactory.create(id=5001)
        self.register()
        self.signin()
        res = self.app_get_json('/account/%s/delete' % user.name)
        assert res.status_code == 403, (res.status_code, res.data)

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account_404_user(self, mock):
        """Test WEB delete account user does not exists"""
        from pybossa.jobs import delete_account
        self.register()
        self.signin()
        res = self.app.get('/account/juan/delete')
        assert res.status_code == 404, res.status_code

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account_json_404_user(self, mock):
        """Test WEB delete account json user does not exist"""
        from pybossa.jobs import delete_account
        self.register()
        self.signin()
        res = self.app_get_json('/account/asdafsdlw/delete')
        assert res.status_code == 404, (res.status_code, res.data)

    @with_context
    @patch('pybossa.view.account.super_queue.enqueue')
    def test_delete_account_json(self, mock):
        """Test WEB JSON delete account works"""
        from pybossa.jobs import delete_account
        self.register()
        self.signin()
        admin = user_repo.get(1)
        user = UserFactory.create(id=100)
        res = self.app_get_json('/account/%s/delete' % user.name)
        data = json.loads(res.data)
        assert data['job'] == 'enqueued', data
        mock.assert_called_with(delete_account, user.id, admin.email_addr)

    @with_context
    def test_42_password_link(self):
        """Test WEB visibility of password change link"""
        self.register()
        self.signin()
        res = self.app.get('/account/johndoe/update')
        assert "Change your Password" in res.data
        user = User.query.get(1)
        user.twitter_user_id = 1234
        db.session.add(user)
        db.session.commit()
        res = self.app.get('/account/johndoe/update')
        assert "Change your Password" not in res.data, res.data

    @with_context
    def test_43_terms_of_use_and_data(self):
        """Test WEB terms of use is working"""
        self.signin_user()
        res = self.app.get('account/register', follow_redirects=True)
        assert "http://okfn.org/terms-of-use/" in res.data, res.data
        assert "http://opendatacommons.org/licenses/by/" in res.data, res.data

    @with_context
    def test_help_endpoint(self):
        """Test WEB help endpoint is working"""
        res = self.app.get('help/', follow_redirects=True)


    @with_context
    @patch('pybossa.view.account.signer.loads')
    def test_44_password_reset_json_key_errors(self, Mock):
        """Test WEB password reset JSON key errors are caught"""
        self.register()
        user = User.query.get(1)
        userdict = {'user': user.name, 'password': user.passwd_hash}
        fakeuserdict = {'user': user.name, 'password': 'wronghash'}
        fakeuserdict_err = {'user': user.name, 'passwd': 'some'}
        fakeuserdict_form = {'user': user.name, 'passwd': 'p4ssw0rD'}
        key = signer.dumps(userdict, salt='password-reset')
        returns = [BadSignature('Fake Error'), BadSignature('Fake Error'), userdict,
                   fakeuserdict, userdict, userdict, fakeuserdict_err]

        def side_effects(*args, **kwargs):
            result = returns.pop(0)
            if isinstance(result, BadSignature):
                raise result
            return result
        Mock.side_effect = side_effects
        # Request with no key
        content_type = 'application/json'
        res = self.app_get_json('/account/reset-password')
        assert 403 == res.status_code
        data = json.loads(res.data)
        assert data.get('code') == 403, data
        # Request with invalid key
        res = self.app_get_json('/account/reset-password?key=foo')
        assert 403 == res.status_code
        data = json.loads(res.data)
        assert data.get('code') == 403, data

        # Request with key exception
        res = self.app_get_json('/account/reset-password?key=%s' % (key))
        assert 403 == res.status_code
        data = json.loads(res.data)
        assert data.get('code') == 403, data

        res = self.app_get_json('/account/reset-password?key=%s' % (key))
        assert 200 == res.status_code
        data = json.loads(res.data)
        assert data.get('form'), data
        assert data.get('form').get('csrf'), data
        keys = ['current_password', 'new_password', 'confirm']
        for key in keys:
            assert key in data.get('form').keys(), data

        res = self.app_get_json('/account/reset-password?key=%s' % (key))
        assert 403 == res.status_code
        data = json.loads(res.data)
        assert data.get('code') == 403, data

        # Check validation
        payload = {'new_password': '', 'confirm': '#4a4'}
        res = self.app_post_json('/account/reset-password?key=%s' % (key),
                                 data=payload)


        msg = "Please correct the errors"
        data = json.loads(res.data)
        assert msg in data.get('flash'), data
        assert data.get('form').get('errors'), data
        assert data.get('form').get('errors').get('new_password'), data


        res = self.app_post_json('/account/reset-password?key=%s' % (key),
                                 data={'new_password': 'p4ssw0rD',
                                       'confirm': 'p4ssw0rD'})
        data = json.loads(res.data)
        msg = "You reset your password successfully!"
        assert msg in data.get('flash'), data
        assert data.get('status') == SUCCESS, data


        # Request without password
        res = self.app_get_json('/account/reset-password?key=%s' % (key))
        assert 403 == res.status_code
        data = json.loads(res.data)
        assert data.get('code') == 403, data

    @with_context
    @patch('pybossa.view.account.signer.loads')
    def test_password_reset_key_page(self, mock_signer_loads):
        """Test WEB password reset key page"""
        self.register()
        res = self.app.get('/account/forgot-password', follow_redirects=True)
        assert res.status_code == 200, res
        user = User.query.get(1)
        res = self.app.post('/account/forgot-password', data={'email': user.email_addr}, follow_redirects=True)
        assert res.status_code == 200, res
        mock_signer_loads.return_value = {}
        res = self.app.post('/account/password-reset-key', data={'password_reset_key': 'asdf'}, follow_redirects=True)
        assert res.status_code == 403, res
        mock_signer_loads.return_value = {'user': user.name, 'password': user.passwd_hash}
        res = self.app.post('/account/password-reset-key', data={'password_reset_key': 'asdf'}, follow_redirects=True)
        assert res.status_code == 200, res

    @with_context
    @patch('pybossa.view.account.signer.loads')
    def test_44_password_reset_key_errors(self, Mock):
        """Test WEB password reset key errors are caught"""
        self.register()
        user = User.query.get(1)
        userdict = {'user': user.name, 'password': user.passwd_hash}
        fakeuserdict = {'user': user.name, 'password': 'wronghash'}
        fakeuserdict_err = {'user': user.name, 'passwd': 'some'}
        fakeuserdict_form = {'user': user.name, 'passwd': 'p4ssw0rD'}
        key = signer.dumps(userdict, salt='password-reset')
        returns = [BadSignature('Fake Error'), BadSignature('Fake Error'), userdict,
                   fakeuserdict, userdict, userdict, fakeuserdict_err]

        def side_effects(*args, **kwargs):
            result = returns.pop(0)
            if isinstance(result, BadSignature):
                raise result
            return result
        Mock.side_effect = side_effects
        # Request with no key
        res = self.app.get('/account/reset-password', follow_redirects=True)
        assert 403 == res.status_code
        # Request with invalid key
        res = self.app.get('/account/reset-password?key=foo', follow_redirects=True)
        assert 403 == res.status_code
        # Request with key exception
        res = self.app.get('/account/reset-password?key=%s' % (key), follow_redirects=True)
        assert 403 == res.status_code
        res = self.app.get('/account/reset-password?key=%s' % (key), follow_redirects=True)
        assert 200 == res.status_code
        res = self.app.get('/account/reset-password?key=%s' % (key), follow_redirects=True)
        assert 403 == res.status_code

        # Check validation
        res = self.app.post('/account/reset-password?key=%s' % (key),
                            data={'new_password': '',
                                  'confirm': '#4a4'},
                            follow_redirects=True)

        assert "Please correct the errors" in res.data, res.data

        res = self.app.post('/account/reset-password?key=%s' % (key),
                            data={'new_password': 'p4ssw0rD',
                                  'confirm': 'p4ssw0rD'},
                            follow_redirects=True)

        assert "You reset your password successfully!" in res.data

        # Request without password
        res = self.app.get('/account/reset-password?key=%s' % (key), follow_redirects=True)
        assert 403 == res.status_code

    @with_context
    @patch('pybossa.view.account.url_for')
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.signer')
    def test_45_password_reset_link_json(self, signer, queue, mock_url):
        """Test WEB password reset email form"""
        csrf = self.get_csrf('/account/forgot-password')
        res = self.app.post('/account/forgot-password',
                            data=json.dumps({'email_addr': "johndoe@example.com"}),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})
        data = json.loads(res.data)
        err_msg = "Mimetype should be application/json"
        assert res.mimetype == 'application/json', err_msg
        err_msg = "Flash message should be included"
        assert data.get('flash'), err_msg
        assert ("We don't have this email in our records. You may have"
                " signed up with a different email") in data.get('flash'), err_msg

        self.register()
        self.register(name='janedoe')
        self.register(name='google')
        self.register(name='facebook')
        user = User.query.get(1)
        jane = User.query.get(2)
        jane.twitter_user_id = 10
        google = User.query.get(3)
        google.google_user_id = 103
        facebook = User.query.get(4)
        facebook.facebook_user_id = 104
        db.session.add_all([jane, google, facebook])
        db.session.commit()

        data = {'password': user.passwd_hash, 'user': user.name}
        csrf = self.get_csrf('/account/forgot-password')
        res = self.app.post('/account/forgot-password',
                            data=json.dumps({'email_addr': user.email_addr}),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})
        resdata = json.loads(res.data)
        signer.dumps.assert_called_with(data, salt='password-reset')
        key = signer.dumps(data, salt='password-reset')
        enqueue_call = queue.enqueue.call_args_list[0]
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg
        enqueue_call = queue.enqueue.call_args_list[4]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'Click here to recover your account' in enqueue_call[0][1]['body']
        assert 'To recover your password' in enqueue_call[0][1]['html']
        assert mock_url.called_with('.reset_password', key=key, _external=True)
        err_msg = "There should be a flash message"
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg

        data = {'password': jane.passwd_hash, 'user': jane.name}
        csrf = self.get_csrf('/account/forgot-password')
        res = self.app.post('/account/forgot-password',
                            data=json.dumps({'email_addr': 'janedoe@example.com'}),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})

        resdata = json.loads(res.data)

        enqueue_call = queue.enqueue.call_args_list[1]
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg
        enqueue_call = queue.enqueue.call_args_list[5]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'your Twitter account to ' in enqueue_call[0][1]['body']
        assert 'your Twitter account to ' in enqueue_call[0][1]['html']
        err_msg = "There should be a flash message"
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg

        data = {'password': google.passwd_hash, 'user': google.name}
        csrf = self.get_csrf('/account/forgot-password')
        res = self.app.post('/account/forgot-password',
                            data=json.dumps({'email_addr': 'google@example.com'}),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})

        resdata = json.loads(res.data)

        enqueue_call = queue.enqueue.call_args_list[2]
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg
        enqueue_call = queue.enqueue.call_args_list[6]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'your Google account to ' in enqueue_call[0][1]['body']
        assert 'your Google account to ' in enqueue_call[0][1]['html']
        err_msg = "There should be a flash message"
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg

        data = {'password': facebook.passwd_hash, 'user': facebook.name}
        csrf = self.get_csrf('/account/forgot-password')
        res = self.app.post('/account/forgot-password',
                            data=json.dumps({'email_addr': 'facebook@example.com'}),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})

        enqueue_call = queue.enqueue.call_args_list[3]
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg
        enqueue_call = queue.enqueue.call_args_list[7]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'your Facebook account to ' in enqueue_call[0][1]['body']
        assert 'your Facebook account to ' in enqueue_call[0][1]['html']
        err_msg = "There should be a flash message"
        assert resdata.get('flash'), err_msg
        assert "sent you an email" in resdata.get('flash'), err_msg

        # Test with not valid form
        csrf = self.get_csrf('/account/forgot-password')
        res = self.app.post('/account/forgot-password',
                            data=json.dumps({'email_addr': ''}),
                            follow_redirects=False,
                            content_type="application/json",
                            headers={'X-CSRFToken': csrf})

        resdata = json.loads(res.data)
        msg = "Something went wrong, please correct the errors"
        assert msg in resdata.get('flash'), res.data
        assert resdata.get('form').get('errors').get('email_addr') is not None, resdata

        with patch.dict(self.flask_app.config, {'SPA_SERVER_NAME':
                                                'http://local.com'}):
            data = {'password': user.passwd_hash, 'user': user.name}
            csrf = self.get_csrf('/account/forgot-password')
            res = self.app.post('/account/forgot-password',
                                data=json.dumps({'email_addr': user.email_addr}),
                                follow_redirects=False,
                                content_type="application/json",
                                headers={'X-CSRFToken': csrf})
            resdata = json.loads(res.data)
            signer.dumps.assert_called_with(data, salt='password-reset')
            key = signer.dumps(data, salt='password-reset')
            enqueue_call = queue.enqueue.call_args_list[-1]
            assert send_mail == enqueue_call[0][0], "send_mail not called"
            assert 'Click here to recover your account' in enqueue_call[0][1]['body']
            assert 'To recover your password' in enqueue_call[0][1]['html']
            assert mock_url.called_with('.reset_password', key=key)
            err_msg = "There should be a flash message"
            assert resdata.get('flash'), err_msg
            assert "sent you an email" in resdata.get('flash'), err_msg


    @with_context
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.signer')
    def test_45_password_reset_link(self, signer, queue):
        """Test WEB password reset email form"""
        res = self.app.post('/account/forgot-password',
                            data={'email_addr': "johndoe@example.com"},
                            follow_redirects=True)
        assert ("We don&#39;t have this email in our records. You may have"
                " signed up with a different email") in res.data

        self.register()
        self.register(name='janedoe')
        self.register(name='google')
        self.register(name='facebook')
        user = User.query.get(1)
        jane = User.query.get(2)
        jane.twitter_user_id = 10
        google = User.query.get(3)
        google.google_user_id = 103
        facebook = User.query.get(4)
        facebook.facebook_user_id = 104
        db.session.add_all([jane, google, facebook])
        db.session.commit()

        data = {'password': user.passwd_hash, 'user': user.name}
        self.app.post('/account/forgot-password',
                      data={'email_addr': user.email_addr},
                      follow_redirects=True)
        signer.dumps.assert_called_with(data, salt='password-reset')
        enqueue_call = queue.enqueue.call_args_list[0]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'Account Registration' in enqueue_call[0][1]['html']
        enqueue_call = queue.enqueue.call_args_list[4]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'Click here to recover your account' in enqueue_call[0][1]['body']
        assert 'To recover your password' in enqueue_call[0][1]['html']

        data = {'password': jane.passwd_hash, 'user': jane.name}
        self.app.post('/account/forgot-password',
                      data={'email_addr': 'janedoe@example.com'},
                      follow_redirects=True)
        enqueue_call = queue.enqueue.call_args_list[1]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'Account Registration' in enqueue_call[0][1]['html']
        enqueue_call = queue.enqueue.call_args_list[5]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'your Twitter account to ' in enqueue_call[0][1]['body']
        assert 'your Twitter account to ' in enqueue_call[0][1]['html']

        data = {'password': google.passwd_hash, 'user': google.name}
        self.app.post('/account/forgot-password',
                      data={'email_addr': 'google@example.com'},
                      follow_redirects=True)
        enqueue_call = queue.enqueue.call_args_list[2]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'Account Registration' in enqueue_call[0][1]['html']
        enqueue_call = queue.enqueue.call_args_list[6]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'your Google account to ' in enqueue_call[0][1]['body']
        assert 'your Google account to ' in enqueue_call[0][1]['html']

        data = {'password': facebook.passwd_hash, 'user': facebook.name}
        self.app.post('/account/forgot-password',
                      data={'email_addr': 'facebook@example.com'},
                      follow_redirects=True)
        enqueue_call = queue.enqueue.call_args_list[3]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'Account Registration' in enqueue_call[0][1]['html']
        enqueue_call = queue.enqueue.call_args_list[7]
        assert send_mail == enqueue_call[0][0], "send_mail not called"
        assert 'your Facebook account to ' in enqueue_call[0][1]['body']
        assert 'your Facebook account to ' in enqueue_call[0][1]['html']

        # Test with not valid form
        res = self.app.post('/account/forgot-password',
                            data={'email_addr': ''},
                            follow_redirects=True)
        msg = "Something went wrong, please correct the errors"
        assert msg in res.data, res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_46_tasks_exists(self, mock):
        """Test WEB tasks page works."""
        self.register()
        self.signin()
        self.new_project()
        res = self.app.get('/project/sampleapp/tasks/', follow_redirects=True)
        assert "Edit the task presenter" in res.data, \
            "Task Presenter Editor should be an option"
        assert_raises(ValueError, json.loads, res.data)

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_46_tasks_exists_json(self, mock):
        """Test WEB tasks json works."""
        self.register()
        self.signin()
        self.new_project()
        res = self.app_get_json('/project/sampleapp/tasks/')
        data = json.loads(res.data)
        err_msg = 'Field missing in data'
        assert 'autoimporter_enabled' in data, err_msg
        assert 'last_activity' in data, err_msg
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_task_runs' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'template' in data, err_msg
        assert 'title' in data, err_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_46_tasks_exists_json_other_user(self, mock):
        """Test WEB tasks json works."""
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        project.published = True
        db.session.commit()
        TaskFactory.create(project=project)
        self.signout()
        self.signin_user(id=2)
        self.app.post('/project/sampleapp/password', data={
            'password': 'Abc01$'
        })
        res = self.app_get_json('/project/sampleapp/tasks/')
        data = json.loads(res.data)
        print(res.data)
        err_msg = 'Field missing in data'
        assert 'autoimporter_enabled' in data, err_msg
        assert 'last_activity' in data, err_msg
        assert 'n_completed_tasks' in data, err_msg
        assert 'n_task_runs' in data, err_msg
        assert 'n_tasks' in data, err_msg
        assert 'n_volunteers' in data, err_msg
        assert 'overall_progress' in data, err_msg
        assert 'owner' in data, err_msg
        assert 'pro_features' in data, err_msg
        assert 'project' in data, err_msg
        assert 'template' in data, err_msg
        assert 'title' in data, err_msg
        err_msg = 'private data should not be exposed'
        assert 'api_key' not in data['owner'], err_msg
        assert 'secret_key' not in data['project'], err_msg


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_47_task_presenter_editor_loads(self, mock):
        """Test WEB task presenter editor loads"""
        self.register()
        self.signin()
        self.new_project()
        res = self.app.get('/project/sampleapp/tasks/taskpresentereditor',
                           follow_redirects=True)
        err_msg = "Task Presenter options not found"
        assert "Task Presenter Editor" in res.data, err_msg
        err_msg = "Basic template not found"
        assert "The most basic template" in res.data, err_msg
        err_msg = "Image Pattern Recognition not found"
        assert "Image Pattern Recognition" in res.data, err_msg
        err_msg = "Sound Pattern Recognition not found"
        assert "Sound Pattern Recognition" in res.data, err_msg
        err_msg = "Video Pattern Recognition not found"
        assert "Video Pattern Recognition" in res.data, err_msg
        err_msg = "Transcribing documents not found"
        assert "Transcribing documents" in res.data, err_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_47_task_presenter_editor_loads_json(self, mock):
        """Test WEB task presenter editor JSON loads"""
        self.register()
        self.signin()
        self.new_project()
        res = self.app_get_json('/project/sampleapp/tasks/taskpresentereditor')
        data = json.loads(res.data)
        err_msg = "Task Presenter options not found"
        assert "Task Presenter Editor" in data['title'], err_msg
        presenters = ["projects/presenters/basic.html",
                      "projects/presenters/image.html",
                      "projects/presenters/sound.html",
                      "projects/presenters/video.html",
                      "projects/presenters/map.html",
                      "projects/presenters/pdf.html"]
        assert data['presenters'] == presenters, err_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_48_task_presenter_editor_works(self, mock):
        """Test WEB task presenter editor works"""
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        err_msg = "Task Presenter should be empty"
        assert not project.info.get('task_presenter'), err_msg

        res = self.app.get('/project/sampleapp/tasks/taskpresentereditor?template=basic',
                           follow_redirects=True)
        assert "var editor" in res.data, "CodeMirror Editor not found"
        assert "Task Presenter" in res.data, "CodeMirror Editor not found"
        assert "Task Presenter Preview" in res.data, "CodeMirror View not found"
        res = self.app.post('/project/sampleapp/tasks/taskpresentereditor',
                            data={'editor': 'Some HTML code!'},
                            follow_redirects=True)
        assert "Sample Project" in res.data, "Does not return to project details"
        project = db.session.query(Project).first()
        err_msg = "Task Presenter failed to update"
        assert project.info['task_presenter'] == 'Some HTML code!', err_msg

        # Check it loads the previous posted code:
        res = self.app.get('/project/sampleapp/tasks/taskpresentereditor',
                           follow_redirects=True)

        assert "Some HTML code" in res.data, res.data

        # Check it doesn't loads the previous posted code:
        res = self.app.get('/project/sampleapp/tasks/taskpresentereditor?template=basic&clear_template=true',
                           follow_redirects=True)
        assert "Some HTML code" not in res.data, res.data


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_48_task_presenter_editor_works_json(self, mock):
        """Test WEB task presenter editor works JSON"""
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        err_msg = "Task Presenter should be empty"
        assert not project.info.get('task_presenter'), err_msg

        url = '/project/sampleapp/tasks/taskpresentereditor?template=basic'
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = "there should not be presenters"
        assert data.get('presenters') is None, err_msg
        assert data['form']['csrf'] is not None, data
        assert data['form']['editor'] is not None, data
        res = self.app_post_json(url, data={'editor': 'Some HTML code!'})
        data = json.loads(res.data)
        assert data['status'] == SUCCESS, data
        project = db.session.query(Project).first()
        assert project.info['task_presenter'] == 'Some HTML code!', err_msg

        # Check it loads the previous posted code:
        res = self.app_get_json(url)
        data = json.loads(res.data)
        assert data['form']['editor'] == 'Some HTML code!', data

    @with_context
    @patch('pybossa.ckan.requests.get')
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    @patch('pybossa.forms.validator.requests.get')
    def test_48_update_app_info(self, Mock, mock, mock_webhook):
        """Test WEB project update/edit works keeping previous info values"""
        html_request = FakeResponse(text=json.dumps(self.pkg_json_not_found),
                                    status_code=200,
                                    headers={'content-type': 'application/json'},
                                    encoding='utf-8')
        Mock.return_value = html_request

        mock_webhook.return_value = html_request
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        err_msg = "Task Presenter should be empty"
        assert not project.info.get('task_presenter'), err_msg

        res = self.app.post('/project/sampleapp/tasks/taskpresentereditor',
                            data={'editor': 'Some HTML code!'},
                            follow_redirects=True)
        assert "Sample Project" in res.data, "Does not return to project details"
        project = db.session.query(Project).first()
        for i in range(10):
            key = "key_%s" % i
            project.info[key] = i
        db.session.add(project)
        db.session.commit()
        _info = project.info

        self.update_project()
        project = db.session.query(Project).first()
        for key in _info:
            assert key in project.info.keys(), \
                "The key %s is lost and it should be here" % key
        assert project.name == "Sample Project", "The project has not been updated"
        error_msg = "The project description has not been updated"
        assert project.description == "Description", error_msg
        error_msg = "The project long description has not been updated"
        assert project.long_description == "Long desc", error_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_49_announcement_messages_levels(self, mock):
        """Test WEB announcement messages works"""
        announcement = AnnouncementFactory.create(published=True, info={'level': 0})
        self.register(admin=True)
        self.signin()
        res = self.app.get("/", follow_redirects=True)
        error_msg = "There should be a message for admin"
        print(res.data)
        assert announcement.title in res.data, error_msg
        assert announcement.body in res.data, error_msg
        self.signout()

        self.register(subadmin=True)
        self.signin()
        res = self.app.get("/", follow_redirects=True)
        error_msg = "There should not be a message for subadmin"
        print(res.data)
        assert announcement.title in res.data, error_msg
        assert announcement.body in res.data, error_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_49_announcement_messages_anonymoususers(self, mock):
        """Test WEB announcement messages works"""
        announcement = AnnouncementFactory.create(published=True, info={'level': 30})
        res = self.app.get("/", follow_redirects=True)
        error_msg = "There should not be a message for anonymous user"
        print(res.data)
        assert announcement.title not in res.data, error_msg
        assert announcement.body not in res.data, error_msg

    @with_context
    def test_export_user_json(self):
        """Test export user data in JSON."""
        user = UserFactory.create()
        from pybossa.core import json_exporter as e
        e._make_zip(None, '', 'personal_data', user.dictize(), user.id,
                    'personal_data.zip')

        uri = "/uploads/user_%s/personal_data.zip" % user.id
        res = self.app.get(uri, follow_redirects=True)
        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 1"
        assert len(zip.namelist()) == 1, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        expected_filename = 'personal_data_.json'
        assert extracted_filename == expected_filename, (zip.namelist()[0],
                                                         expected_filename)
        exported_user = json.loads(zip.read(extracted_filename))
        assert exported_user['id'] == user.id

    @with_context
    def test_export_user_link(self):
        """Test WEB export user data link only for owner."""
        root, user, other = UserFactory.create_batch(3)
        uri = 'account/%s/export' % user.name
        # As anon
        res = self.app.get(uri)
        assert res.status_code == 302

        # As admin
        res = self.app.get(uri + '?api_key=%s' % root.api_key,
                           follow_redirects=True)
        assert res.status_code == 200, res.status_code

        # As other
        res = self.app.get(uri + '?api_key=%s' % other.api_key,
                           follow_redirects=True)
        assert res.status_code == 403, res.status_code

        # As owner
        res = self.app.get(uri + '?api_key=%s' % user.api_key,
                           follow_redirects=True)
        assert res.status_code == 403, res.status_code

        # As non existing user
        uri = 'account/algo/export'
        res = self.app.get(uri + '?api_key=%s' % user.api_key,
                           follow_redirects=True)
        assert res.status_code == 403, res.status_code


    @with_context
    def test_export_user_link_json(self):
        """Test WEB export user data link only for owner as JSON."""
        root, user, other = UserFactory.create_batch(3)
        uri = 'account/%s/export' % user.name
        # As anon
        res = self.app_get_json(uri)
        assert res.status_code == 302

        # As admin
        res = self.app_get_json(uri + '?api_key=%s' % root.api_key,
                                follow_redirects=True)
        assert res.status_code == 200, res.status_code

        # As other
        res = self.app_get_json(uri + '?api_key=%s' % other.api_key,
                                follow_redirects=True)
        assert res.status_code == 403, res.status_code

        # As owner
        res = self.app_get_json(uri + '?api_key=%s' % user.api_key,
                                follow_redirects=True)
        assert res.status_code == 403, res.status_code

        # As non existing user
        uri = 'account/algo/export'
        res = self.app_get_json(uri + '?api_key=%s' % user.api_key,
                                follow_redirects=True)
        assert res.status_code == 403, res.status_code


    @with_context
    @patch('pybossa.exporter.uploader.delete_file')
    @patch('pybossa.exporter.json_export.scheduler.enqueue_in')
    @patch('pybossa.exporter.json_export.uuid.uuid1', return_value='random')
    def test_export_user_json(self, m1, m2, m3):
        """Test export user data in JSON."""
        user = UserFactory.create(id=50423)
        from pybossa.core import json_exporter as e
        e._make_zip(None, '', 'personal_data', user.dictize(), user.id,
                    'personal_data.zip')

        uri = "/uploads/user_%s/random_sec_personal_data.zip" % user.id
        print(uri)
        res = self.app.get(uri, follow_redirects=True)
        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 1"
        assert len(zip.namelist()) == 1, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        expected_filename = 'personal_data_.json'
        assert extracted_filename == expected_filename, (zip.namelist()[0],
                                                         expected_filename)
        exported_user = json.loads(zip.read(extracted_filename))
        assert exported_user['id'] == user.id

        container = 'user_%s' % user.id
        import datetime
        m2.assert_called_with(datetime.timedelta(3),
                              m3,
                              'random_sec_personal_data.zip',
                              container)

    @with_context
    def test_export_result_json(self):
        """Test WEB export Results to JSON works"""
        project = ProjectFactory.create()
        tasks = TaskFactory.create_batch(5, project=project, n_answers=1)
        for task in tasks:
            TaskRunFactory.create(task=task, project=project)
        results = result_repo.filter_by(project_id=project.id)
        for result in results:
            result.info = dict(key='value')
            result_repo.update(result)

        # First test for a non-existant project
        self.signin_user(id=42)
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the results in JSON format
        uri = "/project/somethingnotexists/tasks/export?type=result&format=json"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        make_subadmin_by(id=42)
        uri = '/project/%s/tasks/export' % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now test that a 404 is raised when an arg is invalid
        uri = "/project/%s/tasks/export?type=ask&format=json" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        uri = "/project/%s/tasks/export?format=json" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        uri = "/project/%s/tasks/export?type=result" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # And a 415 is raised if the requested format is not supported or invalid
        uri = "/project/%s/tasks/export?type=result&format=gson" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '415 UNSUPPORTED MEDIA TYPE', res.status

        # Now get the tasks in JSON format
        self.clear_temp_container(1)   # Project ID 1 is assumed here. See project.id below.
        uri = "/project/%s/tasks/export?type=result&format=json" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  #export handled by email

        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 1"
        assert len(zip.namelist()) == 1, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        expected_filename = '%s_result.json' % unidecode(project.short_name)
        assert extracted_filename == expected_filename, (zip.namelist()[0],
                                                         expected_filename)

        exported_results = json.loads(zip.read(extracted_filename))
        assert len(exported_results) == len(results), (len(exported_results),
                                                            len(project.tasks))
        for er in exported_results:
            er['info']['key'] == 'value'
        # Results are exported as an attached file
        content_disposition = 'attachment; filename=%d_%s_result_json.zip' % (project.id,
                                                                              unidecode(project.short_name))
        assert res.headers.get('Content-Disposition') == content_disposition, res.headers


    @with_context
    def test_50_export_task_json(self):
        """Test WEB export Tasks to JSON works"""
        self.register()
        self.signin()
        Fixtures.create()
        # First test for a non-existant project
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in JSON format
        uri = "/project/somethingnotexists/tasks/export?type=task&format=json"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        uri = '/project/%s/tasks/export' % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now test that a 404 is raised when an arg is invalid
        uri = "/project/%s/tasks/export?type=ask&format=json" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        uri = "/project/%s/tasks/export?format=json" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        uri = "/project/%s/tasks/export?type=task" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # And a 415 is raised if the requested format is not supported or invalid
        uri = "/project/%s/tasks/export?type=task&format=gson" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '415 UNSUPPORTED MEDIA TYPE', res.status

        # Now get the tasks in JSON format
        self.clear_temp_container(1)   # Project ID 1 is assumed here. See project.id below.
        uri = "/project/%s/tasks/export?type=task&format=json" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        '''
        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 1"
        assert len(zip.namelist()) == 1, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        assert extracted_filename == 'test-app_task.json', zip.namelist()[0]

        exported_tasks = json.loads(zip.read(extracted_filename))
        project = db.session.query(Project)\
            .filter_by(short_name=Fixtures.project_short_name)\
            .first()
        err_msg = "The number of exported tasks is different from Project Tasks"
        assert len(exported_tasks) == len(project.tasks), err_msg
        # Tasks are exported as an attached file
        content_disposition = 'attachment; filename=%d_test-app_task_json.zip' % project.id
        assert res.headers.get('Content-Disposition') == content_disposition, res.headers
        '''
        assert "You will be emailed when your export has been completed." in res.data

    @with_context
    def test_export_task_json_support_non_latin1_project_names(self):
        self.register()
        self.signin()
        owner = UserFactory.create(email_addr='xyz@a.com', admin=True, id=999)
        project = ProjectFactory.create(name=u'Измени Киев!', short_name=u'Измени Киев!')
        self.clear_temp_container(project.owner_id)
        res = self.app.get('project/%s/tasks/export?type=task&format=json' % project.short_name,
                           follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  # export is handled by email
        filename = secure_filename(unidecode(u'Измени Киев!'))
        assert filename in res.headers.get('Content-Disposition'), res.headers

    @with_context
    def test_export_taskrun_json_support_non_latin1_project_names(self):
        self.register()
        self.signin()
        owner = UserFactory.create(email_addr='xyz@a.com', admin=True, id=999)
        project = ProjectFactory.create(name=u'Измени Киев!', short_name=u'Измени Киев!')
        self.signin(email=owner.email_addr, password='1234')
        res = self.app.get('project/%s/tasks/export?type=task_run&format=json' % project.short_name,
                           follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  # export is handled by email
        filename = secure_filename(unidecode(u'Измени Киев!'))
        assert filename in res.headers.get('Content-Disposition'), res.headers

    @with_context
    def test_export_task_csv_support_non_latin1_project_names(self):
        self.register()
        self.signin()
        owner = UserFactory.create(email_addr='xyz@a.com', admin=True, id=999)
        project = ProjectFactory.create(name=u'Измени Киев!', short_name=u'Измени Киев!', owner=owner)
        self.signin(email=owner.email_addr, password='1234')
        self.clear_temp_container(project.owner_id)
        res = self.app.get('/project/%s/tasks/export?type=task&format=csv' % project.short_name,
                           follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  #export handled by email
        filename = secure_filename(unidecode(u'Измени Киев!'))
        assert filename in res.headers.get('Content-Disposition'), res.headers

    @with_context
    def test_export_taskrun_csv_support_non_latin1_project_names(self):
        self.register()
        self.signin()
        owner = UserFactory.create(email_addr='xyz@a.com', admin=True, id=999)
        project = ProjectFactory.create(name=u'Измени Киев!', short_name=u'Измени Киев!')
        self.signin(email=owner.email_addr, password='1234')
        task = TaskFactory.create(project=project)
        TaskRunFactory.create(task=task)
        res = self.app.get('/project/%s/tasks/export?type=task_run&format=csv' % project.short_name,
                           follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  #export handled by email
        filename = secure_filename(unidecode(u'Измени Киев!'))
        assert filename in res.headers.get('Content-Disposition'), res.headers

    @with_context
    def test_export_taskruns_json(self):
        """Test WEB export Task Runs to JSON works"""
        self.register()
        self.signin()
        Fixtures.create()
        # First test for a non-existant project
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in JSON format
        uri = "/project/somethingnotexists/tasks/export?type=task&format=json"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        self.clear_temp_container(1)   # Project ID 1 is assumed here. See project.id below.
        uri = '/project/%s/tasks/export' % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now get the tasks in JSON format
        uri = "/project/%s/tasks/export?type=task_run&format=json" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  #export handled by email
        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 1"
        assert len(zip.namelist()) == 1, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        assert extracted_filename == 'test-app_task_run.json', zip.namelist()[0]

        exported_task_runs = json.loads(zip.read(extracted_filename))
        project = db.session.query(Project)\
                    .filter_by(short_name=Fixtures.project_short_name)\
                    .first()
        err_msg = "The number of exported task runs is different from Project Tasks"
        assert len(exported_task_runs) == len(project.task_runs), err_msg
        # Task runs are exported as an attached file
        content_disposition = 'attachment; filename=%d_test-app_task_run_json.zip' % project.id
        assert res.headers.get('Content-Disposition') == content_disposition, res.headers

    @with_context
    def test_export_task_json_no_tasks_returns_file_with_empty_list(self):
        """Test WEB export Tasks to JSON returns empty list if no tasks in project"""
        self.register()
        self.signin()
        owner = UserFactory.create(email_addr='xyz@a.com', admin=True, id=999)
        project = ProjectFactory.create(owner=owner, short_name='no_tasks_here')
        uri = "/project/%s/tasks/export?type=task&format=json" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  #export handled by email
        zip = zipfile.ZipFile(StringIO(res.data))
        extracted_filename = zip.namelist()[0]

        exported_task_runs = json.loads(zip.read(extracted_filename))

        assert exported_task_runs == [], exported_task_runs

    @with_context
    def test_export_result_csv_with_no_keys(self):
        """Test WEB export Results to CSV with no keys works"""
        # First test for a non-existant project
        uri = '/project/somethingnotexists/tasks/export'
        self.register()
        self.signin()
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CSV format
        uri = "/project/somethingnotexists/tasks/export?type=result&format=csv"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the wrong table name in CSV format
        uri = "/project/%s/tasks/export?type=wrong&format=csv" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        owner = UserFactory.create(id=100)
        project = ProjectFactory.create(owner=owner)
        self.clear_temp_container(project.owner_id)
        tasks = TaskFactory.create_batch(5, project=project,
                                         n_answers=1)
        for task in tasks:
            TaskRunFactory.create(project=project,
                                  info=[["2001", "1000"], [None, None]],
                                  task=task)

        # Get results and update them
        results = result_repo.filter_by(project_id=project.id)
        for result in results:
            result.info = [["2001", "1000"], [None, None]]
            result_repo.update(result)

        uri = '/project/%s/tasks/export' % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        data = res.data.decode('utf-8')
        assert heading in data, "Export page should be available\n %s" % data
        # Now get the tasks in CSV format
        uri = "/project/%s/tasks/export?type=result&format=csv" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert 'You will be emailed when your export has been completed' in res.data
        return

        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 2"
        assert len(zip.namelist()) == 2, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        assert extracted_filename == 'project1_result.csv', zip.namelist()[0]

        csv_content = StringIO(zip.read(extracted_filename))
        csvreader = unicode_csv_reader(csv_content)
        project = db.session.query(Project)\
                    .filter_by(short_name=project.short_name)\
                    .first()
        exported_results = []
        n = 0
        for row in csvreader:
            if n != 0:
                exported_results.append(row)
            else:
                keys = row
            n = n + 1
        err_msg = "The number of exported results is different from Project Results"
        assert len(exported_results) == len(project.tasks), err_msg
        results = db.session.query(Result)\
                    .filter_by(project_id=project.id).all()
        for t in results:
            err_msg = "All the result column names should be included"
            d = t.dictize()
            task_run_ids = d['task_run_ids']
            fl = flatten(t.dictize(), root_keys_to_ignore='task_run_ids')
            fl['task_run_ids'] = task_run_ids
            for tk in fl.keys():
                expected_key = "%s" % tk
                assert expected_key in keys, (err_msg, expected_key, keys)
            err_msg = "All the result.info column names should be included"
            assert type(t.info) == list

        for et in exported_results:
            result_id = et[keys.index('id')]
            result = db.session.query(Result).get(result_id)
            result_dict = result.dictize()
            task_run_ids = result_dict['task_run_ids']
            result_dict_flat = flatten(result_dict,
                                       root_keys_to_ignore='task_run_ids')
            result_dict_flat['task_run_ids'] = task_run_ids
            for k in result_dict_flat.keys():
                slug = '%s' % k
                err_msg = "%s != %s" % (result_dict_flat[k],
                                        et[keys.index(slug)])
                if result_dict_flat[k] is not None:
                    assert unicode(result_dict_flat[k]) == et[keys.index(slug)], err_msg
                else:
                    assert u'' == et[keys.index(slug)], err_msg
        # Tasks are exported as an attached file
        content_disposition = 'attachment; filename=%d_project1_result_csv.zip' % project.id
        assert res.headers.get('Content-Disposition') == content_disposition, res.headers

    @with_context
    def test_export_result_csv(self):
        """Test WEB export Results to CSV works"""
        # First test for a non-existant project
        self.signin_user(id=42)
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CSV format
        uri = "/project/somethingnotexists/tasks/export?type=result&format=csv"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the wrong table name in CSV format
        uri = "/project/%s/tasks/export?type=wrong&format=csv" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        project = ProjectFactory.create()
        self.clear_temp_container(project.owner_id)
        tasks = TaskFactory.create_batch(5, project=project,
                                         n_answers=1)
        for task in tasks:
            TaskRunFactory.create(project=project,
                                  info={'question': task.id},
                                  task=task)

        # Get results and update them
        results = result_repo.filter_by(project_id=project.id)
        for result in results:
            result.info = dict(key='value')
            result_repo.update(result)

        uri = '/project/%s/tasks/export' % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        data = res.data.decode('utf-8')
        assert heading in data, "Export page should be available\n %s" % data
        # Now get the tasks in CSV format
        uri = "/project/%s/tasks/export?type=result&format=csv" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  #export handled by email
        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 2"
        assert len(zip.namelist()) == 2, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        assert extracted_filename == 'project1_result.csv', zip.namelist()[0]

        csv_content = StringIO(zip.read(extracted_filename))
        csvreader = unicode_csv_reader(csv_content)
        project = db.session.query(Project)\
                    .filter_by(short_name=project.short_name)\
                    .first()
        exported_results = []
        n = 0
        for row in csvreader:
            if n != 0:
                exported_results.append(row)
            else:
                keys = row
            n = n + 1
        err_msg = "The number of exported results is different from Project Results"
        assert len(exported_results) == len(project.tasks), err_msg
        results = db.session.query(Result)\
                    .filter_by(project_id=project.id).all()
        for t in results:
            err_msg = "All the result column names should be included"
            print(t)
            d = t.dictize()
            task_run_ids = d['task_run_ids']
            fl = flatten(t.dictize(), root_keys_to_ignore='task_run_ids')
            fl['task_run_ids'] = task_run_ids
            # keys.append('result_id')
            print(fl)
            for tk in fl.keys():
                expected_key = "%s" % tk
                assert expected_key in keys, (err_msg, expected_key, keys)
            err_msg = "All the result.info column names should be included"
            for tk in t.info.keys():
                expected_key = "info_%s" % tk
                assert expected_key in keys, err_msg

        for et in exported_results:
            result_id = et[keys.index('id')]
            result = db.session.query(Result).get(result_id)
            result_dict = result.dictize()
            task_run_ids = result_dict['task_run_ids']
            result_dict_flat = flatten(result_dict,
                                       root_keys_to_ignore='task_run_ids')
            result_dict_flat['task_run_ids'] = task_run_ids
            for k in result_dict_flat.keys():
                slug = '%s' % k
                err_msg = "%s != %s" % (result_dict_flat[k],
                                        et[keys.index(slug)])
                if result_dict_flat[k] is not None:
                    assert unicode(result_dict_flat[k]) == et[keys.index(slug)], err_msg
                else:
                    assert u'' == et[keys.index(slug)], err_msg
            for k in result_dict['info'].keys():
                slug = 'info_%s' % k
                err_msg = "%s != %s" % (result_dict['info'][k], et[keys.index(slug)])
                assert unicode(result_dict_flat[slug]) == et[keys.index(slug)], err_msg
        # Tasks are exported as an attached file
        content_disposition = 'attachment; filename=%d_project1_result_csv.zip' % project.id
        assert res.headers.get('Content-Disposition') == content_disposition, res.headers

    @with_context
    def test_export_task_csv_ignore_keys(self):
        """Test WEB export Tasks to CSV with ignore keys works"""
        # First test for a non-existant project
        with patch.dict(self.flask_app.config, {'IGNORE_FLAT_KEYS': ['geojson']}):
            self.signin_user(id=42)
            uri = '/project/somethingnotexists/tasks/export'
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status
            # Now get the tasks in CSV format
            uri = "/project/somethingnotexists/tasks/export?type=task&format=csv"
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status
            # Now get the wrong table name in CSV format
            uri = "/project/%s/tasks/export?type=wrong&format=csv" % Fixtures.project_short_name
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status

            # Now with a real project
            project = ProjectFactory.create()
            self.clear_temp_container(project.owner_id)

            TaskFactory.create_batch(5, project=project, info={'question': 'qu',
                                                               'geojson':
                                                               'complexjson'})
            # Empty task that should be handled as well.
            TaskFactory.create(project=project, info=None)
            uri = '/project/%s/tasks/export' % project.short_name
            res = self.app.get(uri, follow_redirects=True)
            heading = "Export All Tasks and Task Runs"
            data = res.data.decode('utf-8')
            assert heading in data, "Export page should be available\n %s" % data
            # Now get the tasks in CSV format
            uri = "/project/%s/tasks/export?type=task&format=csv" % project.short_name
            res = self.app.get(uri, follow_redirects=True)
            assert res.status_code == 200, res.status
            assert 'You will be emailed when your export has been completed.' in res.data
            return  #export handled by email

            zip = zipfile.ZipFile(StringIO(res.data))
            # Check only one file in zipfile
            err_msg = "filename count in ZIP is not 2"
            assert len(zip.namelist()) == 2, err_msg
            # Check ZIP filename
            extracted_filename = zip.namelist()[0]
            assert extracted_filename == 'project1_task.csv', zip.namelist()[0]

            csv_content = StringIO(zip.read(extracted_filename))
            csvreader = unicode_csv_reader(csv_content)
            project = db.session.query(Project)\
                        .filter_by(short_name=project.short_name)\
                        .first()
            exported_tasks = []
            n = 0
            for row in csvreader:
                if n != 0:
                    exported_tasks.append(row)
                else:
                    keys = row
                n = n + 1
            err_msg = "The number of exported tasks is different from Project Tasks"
            assert len(exported_tasks) == len(project.tasks), err_msg
            for t in project.tasks:
                err_msg = "All the task column names should be included"
                d = copy.deepcopy(t.dictize())
                if d['info']:
                    d['info'].pop('geojson', None)
                for tk in flatten(d).keys():
                    expected_key = "%s" % tk
                    assert expected_key in keys, (expected_key, err_msg)
                err_msg = "All the task.info column names should be included except geojson"
                info_keys = None
                if t.info:
                    info_keys = copy.deepcopy(t.info.keys())
                    info_keys.pop(info_keys.index('geojson'))
                    for tk in info_keys:
                        expected_key = "info_%s" % tk
                        assert expected_key in keys, (expected_key, err_msg)

            for et in exported_tasks:
                task_id = et[keys.index('id')]
                task = db.session.query(Task).get(task_id)
                task_dict = copy.deepcopy(task.dictize())
                if task_dict['info']:
                    task_dict['info'].pop('geojson', None)
                    task_dict_flat = copy.deepcopy(flatten(task_dict))
                    for k in task_dict_flat.keys():
                        slug = '%s' % k
                        err_msg = "%s != %s" % (task_dict_flat[k], et[keys.index(slug)])
                        if task_dict_flat[k] is not None:
                            assert unicode(task_dict_flat[k]) == et[keys.index(slug)], err_msg
                        else:
                            assert u'' == et[keys.index(slug)], err_msg
                    for k in task_dict['info'].keys():
                        slug = 'info_%s' % k
                        err_msg = "%s != %s" % (task_dict['info'][k], et[keys.index(slug)])
                        assert unicode(task_dict_flat[slug]) == et[keys.index(slug)], err_msg
            # Tasks are exported as an attached file
            content_disposition = 'attachment; filename=%d_project1_task_csv.zip' % project.id
            assert res.headers.get('Content-Disposition') == content_disposition, res.headers


    @with_context
    def test_export_task_csv_new_root_key_without_keys(self):
        """Test WEB export Tasks to CSV new root key without keys works"""
        # Fixtures.create()
        # First test for a non-existant project
        self.register()
        self.signin()
        with patch.dict(self.flask_app.config, {'TASK_CSV_EXPORT_INFO_KEY':'answer'}):
            uri = '/project/somethingnotexists/tasks/export'
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status
            # Now get the tasks in CSV format
            uri = "/project/somethingnotexists/tasks/export?type=task&format=csv"
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status
            # Now get the wrong table name in CSV format
            uri = "/project/%s/tasks/export?type=wrong&format=csv" % Fixtures.project_short_name
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status

            # Now with a real project
            owner = UserFactory.create(id=199)
            project = ProjectFactory.create(owner=owner)
            self.clear_temp_container(project.owner_id)
            for i in range(0, 5):
                task = TaskFactory.create(project=project,
                                          info=[[1,2]])
            uri = '/project/%s/tasks/export' % project.short_name

            res = self.app.get(uri, follow_redirects=True)
            heading = "Export All Tasks and Task Runs"
            data = res.data.decode('utf-8')
            assert heading in data, "Export page should be available\n %s" % data
            # Now get the tasks in CSV format
            uri = "/project/%s/tasks/export?type=task&format=csv" % project.short_name
            res = self.app.get(uri, follow_redirects=True)
            assert 'You will be emailed when your export has been completed' in res.data
            return

            file_name = '/tmp/task_%s.zip' % project.short_name
            with open(file_name, 'w') as f:
                f.write(res.data)
            zip = zipfile.ZipFile(file_name, 'r')
            zip.extractall('/tmp')
            # Check only one file in zipfile
            err_msg = "filename count in ZIP is not 2"
            assert len(zip.namelist()) == 2, err_msg
            # Check ZIP filename
            extracted_filename = zip.namelist()[1]
            assert extracted_filename == 'project1_task_info_only.csv', zip.namelist()[1]

            csv_content = codecs.open('/tmp/' + extracted_filename, 'r', 'utf-8')

            csvreader = unicode_csv_reader(csv_content)
            project = db.session.query(Project)\
                        .filter_by(short_name=project.short_name)\
                        .first()
            exported_tasks = []
            n = 0
            for row in csvreader:
                if n != 0:
                    exported_tasks.append(row)
                else:
                    keys = row
                n = n + 1
            err_msg = "The number of exported tasks should be 0 as there are no keys"
            assert len(exported_tasks) == 0, (err_msg,
                                              len(exported_tasks),
                                              0)
            # Tasks are exported as an attached file
            content_disposition = 'attachment; filename=%d_project1_task_csv.zip' % project.id
            assert res.headers.get('Content-Disposition') == content_disposition, res.headers



    @with_context
    def test_export_task_csv_new_root_key(self):
        """Test WEB export Tasks to CSV new root key works"""
        # Fixtures.create()
        # First test for a non-existant project
        self.register()
        self.signin()
        with patch.dict(self.flask_app.config, {'TASK_CSV_EXPORT_INFO_KEY':'answer'}):
            uri = '/project/somethingnotexists/tasks/export'
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status
            # Now get the tasks in CSV format
            uri = "/project/somethingnotexists/tasks/export?type=task&format=csv"
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status
            # Now get the wrong table name in CSV format
            uri = "/project/%s/tasks/export?type=wrong&format=csv" % Fixtures.project_short_name
            res = self.app.get(uri, follow_redirects=True)
            assert res.status == '404 NOT FOUND', res.status

            # Now with a real project
            owner = UserFactory.create(id=199)
            project = ProjectFactory.create(owner=owner)
            self.clear_temp_container(project.owner_id)
            for i in range(0, 5):
                task = TaskFactory.create(project=project,
                                          info={u'answer':[{u'eñe': i}]})
            uri = '/project/%s/tasks/export' % project.short_name

            res = self.app.get(uri, follow_redirects=True)
            heading = "Export All Tasks and Task Runs"
            data = res.data.decode('utf-8')
            assert heading in data, "Export page should be available\n %s" % data
            # Now get the tasks in CSV format
            uri = "/project/%s/tasks/export?type=task&format=csv" % project.short_name
            res = self.app.get(uri, follow_redirects=True)
            assert 'You will be emailed when your export has been completed' in res.data
            return

            file_name = '/tmp/task_%s.zip' % project.short_name
            with open(file_name, 'w') as f:
                f.write(res.data)
            zip = zipfile.ZipFile(file_name, 'r')
            zip.extractall('/tmp')
            # Check only one file in zipfile
            err_msg = "filename count in ZIP is not 2"
            assert len(zip.namelist()) == 2, err_msg
            # Check ZIP filename
            extracted_filename = zip.namelist()[1]
            assert extracted_filename == 'project1_task_info_only.csv', zip.namelist()[1]

            csv_content = codecs.open('/tmp/' + extracted_filename, 'r', 'utf-8')

            csvreader = unicode_csv_reader(csv_content)
            project = db.session.query(Project)\
                        .filter_by(short_name=project.short_name)\
                        .first()
            exported_tasks = []
            n = 0
            for row in csvreader:
                if n != 0:
                    exported_tasks.append(row)
                else:
                    keys = row
                n = n + 1
            err_msg = "The number of exported tasks is different from Project Tasks"
            assert len(exported_tasks) == len(project.tasks), (err_msg,
                                                               len(exported_tasks),
                                                               len(project.tasks))
            for t in project.tasks:
                err_msg = "All the task column names should be included"
                for tk in flatten(t.info['answer'][0]).keys():
                    expected_key = "%s" % tk
                    assert expected_key in keys, (expected_key, err_msg)

            for et in exported_tasks:
                task_id = et[keys.index('task_id')]
                task = db.session.query(Task).get(task_id)
                task_dict_flat = flatten(task.info['answer'][0])
                task_dict = task.dictize()
                for k in task_dict_flat.keys():
                    slug = '%s' % k
                    err_msg = "%s != %s" % (task_dict_flat[k], et[keys.index(slug)])
                    if task_dict_flat[k] is not None:
                        assert unicode(task_dict_flat[k]) == et[keys.index(slug)], err_msg
                    else:
                        assert u'' == et[keys.index(slug)], err_msg
                for datum in task_dict['info']['answer']:
                    for k in datum.keys():
                        slug = '%s' % k
                        assert unicode(task_dict_flat[slug]) == et[keys.index(slug)], err_msg
            # Tasks are exported as an attached file
            content_disposition = 'attachment; filename=%d_project1_task_csv.zip' % project.id
            assert res.headers.get('Content-Disposition') == content_disposition, res.headers


    @with_context
    def test_export_task_csv(self):
        """Test WEB export Tasks to CSV works"""
        # Fixtures.create()
        # First test for a non-existant project
        self.signin_user(id=42)
        make_subadmin_by(id=42)
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CSV format
        uri = "/project/somethingnotexists/tasks/export?type=task&format=csv"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the wrong table name in CSV format
        uri = "/project/%s/tasks/export?type=wrong&format=csv" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        project = ProjectFactory.create()
        self.clear_temp_container(project.owner_id)
        for i in range(0, 5):
            task = TaskFactory.create(project=project, info={u'eñe': i})
        uri = '/project/%s/tasks/export' % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        data = res.data.decode('utf-8')
        assert heading in data, "Export page should be available\n %s" % data
        # Now get the tasks in CSV format
        uri = "/project/%s/tasks/export?type=task&format=csv" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        assert res.status_code == 200, res.status
        assert 'You will be emailed when your export has been completed.' in res.data
        return  #export handled by email

        file_name = '/tmp/task_%s.zip' % project.short_name
        with open(file_name, 'w') as f:
            f.write(res.data)
        zip = zipfile.ZipFile(file_name, 'r')
        zip.extractall('/tmp')
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 2"
        assert len(zip.namelist()) == 2, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        assert extracted_filename == 'test-app_task.csv', zip.namelist()[0]

        csv_content = codecs.open('/tmp/' + extracted_filename, 'r', 'utf-8')

        csvreader = unicode_csv_reader(csv_content)
        project = db.session.query(Project)\
                    .filter_by(short_name=project.short_name)\
                    .first()
        exported_tasks = []
        n = 0
        for row in csvreader:
            if n != 0:
                exported_tasks.append(row)
            else:
                keys = row
            n = n + 1
        err_msg = "The number of exported tasks is different from Project Tasks"
        assert len(exported_tasks) == len(project.tasks), (err_msg,
                                                           len(exported_tasks),
                                                           len(project.tasks))
        for t in project.tasks:
            err_msg = "All the task column names should be included"
            for tk in flatten(t.dictize()).keys():
                expected_key = "%s" % tk
                assert expected_key in keys, (expected_key, err_msg)
            err_msg = "All the task.info column names should be included"
            for tk in t.info.keys():
                expected_key = "info_%s" % tk
                assert expected_key in keys, (err_msg, expected_key, keys)

        for et in exported_tasks:
            task_id = et[keys.index('id')]
            task = db.session.query(Task).get(task_id)
            task_dict_flat = flatten(task.dictize())
            task_dict = task.dictize()
            for k in task_dict_flat.keys():
                slug = '%s' % k
                err_msg = "%s != %s" % (task_dict_flat[k], et[keys.index(slug)])
                if task_dict_flat[k] is not None:
                    assert unicode(task_dict_flat[k]) == et[keys.index(slug)], err_msg
                else:
                    assert u'' == et[keys.index(slug)], err_msg
            for k in task_dict['info'].keys():
                slug = 'info_%s' % k
                err_msg = "%s != %s" % (task_dict['info'][k], et[keys.index(slug)])
                assert unicode(task_dict_flat[slug]) == et[keys.index(slug)], err_msg
        # Tasks are exported as an attached file
        content_disposition = 'attachment; filename=%d_test-app_task_csv.zip' % project.id
        assert res.headers.get('Content-Disposition') == content_disposition, res.headers

    @nottest
    @with_context
    def test_export_result_csv_no_tasks_returns_empty_file(self):
        """Test WEB export Result to CSV returns empty file if no results in
        project."""
        project = ProjectFactory.create(short_name='no_tasks_here')
        uri = "/project/%s/tasks/export?type=result&format=csv" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        zip = zipfile.ZipFile(StringIO(res.data))
        extracted_filename = zip.namelist()[0]

        csv_content = StringIO(zip.read(extracted_filename))
        csvreader = unicode_csv_reader(csv_content)
        is_empty = True
        for line in csvreader:
            is_empty = False, line

        assert is_empty

    @nottest
    @with_context
    def test_export_task_csv_no_tasks_returns_empty_file(self):
        """Test WEB export Tasks to CSV returns empty file if no tasks in project.
        """
        self.register()
        self.signin()
        Fixtures.create()
        project = db.session.query(Project)\
            .filter_by(short_name=Fixtures.project_short_name)\
            .first()
        uri = "/project/%s/tasks/export?type=task&format=csv" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        zip = zipfile.ZipFile(StringIO(res.data))
        extracted_filename = zip.namelist()[0]

        csv_content = StringIO(zip.read(extracted_filename))
        csvreader = unicode_csv_reader(csv_content)
        is_empty = True
        for line in csvreader:
            is_empty = False, line

        assert is_empty

    @with_context
    def test_53_export_task_runs_csv(self):
        """Test WEB export Task Runs to CSV works"""
        # First test for a non-existant project
        self.register()
        self.signin()
        Fixtures.create()
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CSV format
        uri = "/project/somethingnotexists/tasks/export?type=tas&format=csv"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        project = db.session.query(Project)\
                    .filter_by(short_name=Fixtures.project_short_name)\
                    .first()
        self.clear_temp_container(project.owner_id)
        uri = '/project/%s/tasks/export' % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        data = res.data.decode('utf-8')
        assert heading in data, "Export page should be available\n %s" % data

        # Now get the tasks in CSV format
        uri = "/project/%s/tasks/export?type=task_run&format=csv" % project.short_name
        res = self.app.get(uri, follow_redirects=True)
        '''
        zip = zipfile.ZipFile(StringIO(res.data))
        # Check only one file in zipfile
        err_msg = "filename count in ZIP is not 2"
        assert len(zip.namelist()) == 2, err_msg
        # Check ZIP filename
        extracted_filename = zip.namelist()[0]
        assert extracted_filename == 'project1_task_run.csv', zip.namelist()[0]
        extracted_filename_info_only = zip.namelist()[1]
        assert extracted_filename_info_only == 'project1_task_run_info_only.csv', zip.namelist()[1]

        csv_content = StringIO(zip.read(extracted_filename))
        csvreader = unicode_csv_reader(csv_content)
        project = db.session.query(Project)\
            .filter_by(short_name=project.short_name)\
            .first()
        exported_task_runs = []
        n = 0
        for row in csvreader:
            if n != 0:
                exported_task_runs.append(row)
            else:
                keys = row
            n = n + 1
        err_msg = "The number of exported task runs is different \
                   from Project Tasks Runs: %s != %s" % (len(exported_task_runs), len(project.task_runs))
        assert len(exported_task_runs) == len(project.task_runs), err_msg

        for t in project.tasks[0].task_runs:
            for tk in flatten(t.dictize()).keys():
                expected_key = "%s" % tk
                assert expected_key in keys, expected_key

        for et in exported_task_runs:
            task_run_id = et[keys.index('id')]
            task_run = db.session.query(TaskRun).get(task_run_id)
            task_run_dict = flatten(task_run.dictize())
            for k in task_run_dict:
                slug = '%s' % k
                err_msg = "%s != %s" % (task_run_dict[k], et[keys.index(slug)])
                if task_run_dict[k] is not None:
                    assert unicode(task_run_dict[k]) == et[keys.index(slug)], err_msg
                else:
                    assert u'' == et[keys.index(slug)], err_msg
        # Task runs are exported as an attached file
        content_disposition = 'attachment; filename=%d_test-app_task_run_csv.zip' % project.id
        assert res.headers.get('Content-Disposition') == content_disposition, res.headers
        '''
        assert "You will be emailed when your export has been completed." in res.data

    @with_context
    @patch('pybossa.view.projects.Ckan', autospec=True)
    def test_export_tasks_ckan_exception(self, mock1):
        mocks = [Mock()]
        from test_ckan import TestCkanModule
        fake_ckn = TestCkanModule()
        package = fake_ckn.pkg_json_found
        package['id'] = 3
        mocks[0].package_exists.return_value = (False,
                                                Exception("CKAN: error",
                                                          "error", 500))
        # mocks[0].package_create.return_value = fake_ckn.pkg_json_found
        # mocks[0].resource_create.return_value = dict(result=dict(id=3))
        # mocks[0].datastore_create.return_value = 'datastore'
        # mocks[0].datastore_upsert.return_value = 'datastore'

        mock1.side_effect = mocks

        """Test WEB Export CKAN Tasks works."""
        self.register()
        self.signin()
        Fixtures.create()
        user = db.session.query(User).filter_by(name=Fixtures.name).first()
        project = db.session.query(Project).first()
        user.ckan_api = 'ckan-api-key'
        project.owner_id = user.id
        db.session.add(user)
        db.session.add(project)
        db.session.commit()

        self.signin(email="johndoe@example.com", password="p4ssw0rd")
        # Now with a real project
        uri = '/project/%s/tasks/export' % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now get the tasks in CKAN format
        uri = "/project/%s/tasks/export?type=task&format=ckan" % Fixtures.project_short_name
        with patch.dict(self.flask_app.config, {'CKAN_URL': 'http://ckan.com'}):
            # First time exporting the package
            res = self.app.get(uri, follow_redirects=True)
            msg = '415 Unsupported Media Type'
            err_msg = "CKAN is unsupported"
            assert msg in res.data, err_msg

    @with_context
    @patch('pybossa.view.projects.Ckan', autospec=True)
    def test_export_tasks_ckan_connection_error(self, mock1):
        mocks = [Mock()]
        from test_ckan import TestCkanModule
        fake_ckn = TestCkanModule()
        package = fake_ckn.pkg_json_found
        package['id'] = 3
        mocks[0].package_exists.return_value = (False, ConnectionError)
        # mocks[0].package_create.return_value = fake_ckn.pkg_json_found
        # mocks[0].resource_create.return_value = dict(result=dict(id=3))
        # mocks[0].datastore_create.return_value = 'datastore'
        # mocks[0].datastore_upsert.return_value = 'datastore'

        mock1.side_effect = mocks

        """Test WEB Export CKAN Tasks works."""
        self.register()
        self.signin()
        Fixtures.create()
        user = db.session.query(User).filter_by(name=Fixtures.name).first()
        project = db.session.query(Project).first()
        user.ckan_api = 'ckan-api-key'
        project.owner_id = user.id
        db.session.add(user)
        db.session.add(project)
        db.session.commit()

        self.signin(email="johndoe@example.com", password="p4ssw0rd")
        #self.signin(email=user.email_addr, password=Fixtures.password)
        # Now with a real project
        uri = '/project/%s/tasks/export' % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now get the tasks in CKAN format
        uri = "/project/%s/tasks/export?type=task&format=ckan" % Fixtures.project_short_name
        with patch.dict(self.flask_app.config, {'CKAN_URL': 'http://ckan.com'}):
            # First time exporting the package
            res = self.app.get(uri, follow_redirects=True)
            msg = '415 Unsupported Media Type'
            err_msg = "CKAN is unsupported"
            assert msg in res.data, err_msg

    @with_context
    @patch('pybossa.view.projects.Ckan', autospec=True)
    def test_task_export_tasks_ckan_first_time(self, mock1):
        """Test WEB Export CKAN Tasks unsupported without an existing package."""
        # Second time exporting the package
        mocks = [Mock()]
        resource = dict(name='task', id=1)
        package = dict(id=3, resources=[resource])
        mocks[0].package_exists.return_value = (None, None)
        mocks[0].package_create.return_value = package
        #mocks[0].datastore_delete.return_value = None
        mocks[0].datastore_create.return_value = None
        mocks[0].datastore_upsert.return_value = None
        mocks[0].resource_create.return_value = dict(result=dict(id=3))
        mocks[0].datastore_create.return_value = 'datastore'
        mocks[0].datastore_upsert.return_value = 'datastore'

        mock1.side_effect = mocks

        self.register()
        self.signin()
        Fixtures.create()
        user = db.session.query(User).filter_by(name=Fixtures.name).first()
        project = db.session.query(Project).first()
        user.ckan_api = 'ckan-api-key'
        project.owner_id = user.id
        db.session.add(user)
        db.session.add(project)
        db.session.commit()

        #self.signin(email=user.email_addr, password=Fixtures.password)
        self.signin(email="johndoe@example.com", password="p4ssw0rd")
        # First test for a non-existant project
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CKAN format
        uri = "/project/somethingnotexists/tasks/export?type=task&format=ckan"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CKAN format
        uri = "/project/somethingnotexists/tasks/export?type=other&format=ckan"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        uri = '/project/%s/tasks/export' % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now get the tasks in CKAN format
        uri = "/project/%s/tasks/export?type=task&format=ckan" % Fixtures.project_short_name
        with patch.dict(self.flask_app.config, {'CKAN_URL': 'http://ckan.com'}):
            # First time exporting the package
            res = self.app.get(uri, follow_redirects=True)
            msg = '415 Unsupported Media Type'
            err_msg = "CKAN is unsupported"
            assert msg in res.data, err_msg

    @with_context
    @patch('pybossa.view.projects.Ckan', autospec=True)
    def test_task_export_tasks_ckan_second_time(self, mock1):
        """Test WEB Export CKAN Tasks works with an existing package."""
        # Second time exporting the package
        mocks = [Mock()]
        resource = dict(name='task', id=1)
        package = dict(id=3, resources=[resource])
        mocks[0].package_exists.return_value = (package, None)
        mocks[0].package_update.return_value = package
        mocks[0].datastore_delete.return_value = None
        mocks[0].datastore_create.return_value = None
        mocks[0].datastore_upsert.return_value = None
        mocks[0].resource_create.return_value = dict(result=dict(id=3))
        mocks[0].datastore_create.return_value = 'datastore'
        mocks[0].datastore_upsert.return_value = 'datastore'

        mock1.side_effect = mocks

        self.register()
        self.signin()
        Fixtures.create()
        user = db.session.query(User).filter_by(name=Fixtures.name).first()
        project = db.session.query(Project).first()
        user.ckan_api = 'ckan-api-key'
        project.owner_id = user.id
        db.session.add(user)
        db.session.add(project)
        db.session.commit()

        self.signin(email="johndoe@example.com", password="p4ssw0rd")
        # First test for a non-existant project
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CKAN format
        uri = "/project/somethingnotexists/tasks/export?type=task&format=ckan"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        uri = '/project/%s/tasks/export' % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now get the tasks in CKAN format
        uri = "/project/%s/tasks/export?type=task&format=ckan" % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)

        '''
        with patch.dict(self.flask_app.config, {'CKAN_URL': 'http://ckan.com'}):
            # First time exporting the package
            res = self.app.get(uri, follow_redirects=True)
            msg = 'Data exported to http://ckan.com'
            err_msg = "Tasks should be exported to CKAN"
            assert msg in res.data, err_msg
        '''

    @with_context
    @patch('pybossa.view.projects.Ckan', autospec=True)
    def test_task_export_tasks_ckan_without_resources(self, mock1):
        """Test WEB Export CKAN Tasks works without resources."""
        mocks = [Mock()]
        package = dict(id=3, resources=[])
        mocks[0].package_exists.return_value = (package, None)
        mocks[0].package_update.return_value = package
        mocks[0].resource_create.return_value = dict(result=dict(id=3))
        mocks[0].datastore_create.return_value = 'datastore'
        mocks[0].datastore_upsert.return_value = 'datastore'

        mock1.side_effect = mocks

        self.register()
        self.signin()
        Fixtures.create()
        user = db.session.query(User).filter_by(name=Fixtures.name).first()
        project = db.session.query(Project).first()
        user.ckan_api = 'ckan-api-key'
        project.owner_id = user.id
        db.session.add(user)
        db.session.add(project)
        db.session.commit()

        #self.signin(email=user.email_addr, password=Fixtures.password)
        self.signin(email="johndoe@example.com", password="p4ssw0rd")
        # First test for a non-existant project
        uri = '/project/somethingnotexists/tasks/export'
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status
        # Now get the tasks in CKAN format
        uri = "/project/somethingnotexists/tasks/export?type=task&format=ckan"
        res = self.app.get(uri, follow_redirects=True)
        assert res.status == '404 NOT FOUND', res.status

        # Now with a real project
        uri = '/project/%s/tasks/export' % Fixtures.project_short_name
        res = self.app.get(uri, follow_redirects=True)
        heading = "Export All Tasks and Task Runs"
        assert heading in res.data, "Export page should be available\n %s" % res.data
        # Now get the tasks in CKAN format
        uri = "/project/%s/tasks/export?type=task&format=ckan" % Fixtures.project_short_name
        #res = self.app.get(uri, follow_redirects=True)
        '''
        with patch.dict(self.flask_app.config, {'CKAN_URL': 'http://ckan.com'}):
            # First time exporting the package
            res = self.app.get(uri, follow_redirects=True)
            msg = 'Data exported to http://ckan.com'
            err_msg = "Tasks should be exported to CKAN"
            assert msg in res.data, err_msg
        '''


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_get_import_tasks_no_params_shows_options_and_templates(self, mock):
        """Test WEB import tasks displays the different importers and template
        tasks"""
        self.register()
        self.signin()
        Fixtures.create()
        self.new_project()
        res = self.app.get('/project/sampleapp/tasks/import', follow_redirects=True)
        err_msg = "There should be a CSV importer"
        assert "type=csv" in res.data, err_msg
        err_msg = "There should be a GDocs importer"
        assert "type=gdocs" in res.data, err_msg
        err_msg = "There should be an Epicollect importer"
        assert "type=epicollect" in res.data, err_msg
        err_msg = "There should be a Flickr importer"
        assert "type=flickr" in res.data, err_msg
        err_msg = "There should be a Dropbox importer"
        assert "type=dropbox" in res.data, err_msg
        err_msg = "There should be a Twitter importer"
        assert "type=twitter" in res.data, err_msg
        err_msg = "There should be an S3 importer"
        assert "type=s3" in res.data, err_msg
        err_msg = "There should be an Image template"
        assert "template=image" in res.data, err_msg
        err_msg = "There should be a Map template"
        assert "template=map" in res.data, err_msg
        err_msg = "There should be a PDF template"
        assert "template=pdf" in res.data, err_msg
        err_msg = "There should be a Sound template"
        assert "template=sound" in res.data, err_msg
        err_msg = "There should be a Video template"
        assert "template=video" in res.data, err_msg

        self.signout()

        self.signin(email=Fixtures.email_addr2, password=Fixtures.password)
        res = self.app.get('/project/sampleapp/tasks/import', follow_redirects=True)
        assert res.status_code == 403, res.status_code

    @with_context
    @patch('pybossa.view.projects.importer.create_tasks')
    @patch('pybossa.view.projects.importer.count_tasks_to_import', return_value=1)
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_get_import_tasks_no_params_shows_options_and_templates_json_owner(self, mock, importer_count, importer_tasks):
        """Test WEB import tasks JSON returns tasks's templates """
        admin, user, owner = UserFactory.create_batch(3)
        make_subadmin(owner)
        project = ProjectFactory.create(owner=owner)
        report = MagicMock()
        report.message = "SUCCESS"
        importer_tasks.return_value = report
        url = '/project/%s/tasks/import?api_key=%s' % (project.short_name, owner.api_key)
        res = self.app_get_json(url)
        data = json.loads(res.data)

        assert data['available_importers'] is not None, data
        importers = ["projects/tasks/epicollect.html",
                     "projects/tasks/csv.html",
                     "projects/tasks/s3.html",
                     "projects/tasks/twitter.html",
                     "projects/tasks/youtube.html",
                     "projects/tasks/gdocs.html",
                     "projects/tasks/dropbox.html",
                     "projects/tasks/flickr.html",
                     "projects/tasks/localCSV.html",
                     "projects/tasks/iiif.html"]
        assert sorted(data['available_importers']) == sorted(importers), data

        importers = ['&type=epicollect',
                     '&type=csv',
                     '&type=s3',
                     '&type=twitter',
                     '&type=youtube',
                     '&type=gdocs',
                     '&type=dropbox',
                     '&type=flickr',
                     '&type=localCSV',
                     '&type=iiif']

        for importer in importers:
            res = self.app_get_json(url + importer)
            data = json.loads(res.data)
            assert data['form']['csrf'] is not None
            if 'epicollect' in importer:
                assert 'epicollect_form' in data['form'].keys(), data
                assert 'epicollect_project' in data['form'].keys(), data
            if 'csv' in importer:
                assert 'csv_url' in data['form'].keys(), data
            if importer == 's3':
                assert 'files' in data['form'].keys(), data
                assert 'bucket' in data['form'].keys(), data
            if 'twitter' in importer:
                assert 'max_tweets' in data['form'].keys(), data
                assert 'source' in data['form'].keys(), data
                assert 'user_credentials' in data['form'].keys(), data
            if 'youtube' in importer:
                assert 'playlist_url' in data['form'].keys(), data
            if 'gdocs' in importer:
                assert 'googledocs_url' in data['form'].keys(), data
            if 'dropbox' in importer:
                assert 'files' in data['form'].keys(), data
            if 'flickr' in importer:
                assert 'album_id' in data['form'].keys(), data
            if 'localCSV' in importer:
                assert 'form_name' in data['form'].keys(), data
            if 'iiif' in importer:
                assert 'manifest_uri' in data['form'].keys(), data

        for importer in importers:
            if 'epicollect' in importer:
                data = dict(epicollect_form='data', epicollect_project='project')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data
            if 'csv' in importer:
                data = dict(csv_url='http://data.com')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                print(data)
                assert data['flash'] == "SUCCESS", data
            if 's3' in importer:
                data = dict(files='data', bucket='bucket')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data
            if 'twitter' in importer:
                data = dict(max_tweets=1, source='bucket', user_credentials='user')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data
            if 'youtube' in importer:
                data = dict(playlist_url='url')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data
            if 'gdocs' in importer:
                data = dict(googledocs_url='http://url.com')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data
            if 'dropbox' in importer:
                data = dict(files='http://domain.com')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data
            if 'flickr' in importer:
                data = dict(album_id=13)
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data
            if 'iiif' in importer:
                data = dict(manifest_uri='http://example.com')
                res = self.app_post_json(url + importer, data=data)
                data = json.loads(res.data)
                assert data['flash'] == "SUCCESS", data


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_get_import_tasks_no_params_shows_options_and_templates_json_admin(self, mock):
        """Test WEB import tasks JSON returns tasks's templates """
        admin, user, owner = UserFactory.create_batch(3)
        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/tasks/import?api_key=%s' % (project.short_name, admin.api_key)
        res = self.app_get_json(url)
        data = json.loads(res.data)

        assert data['available_importers'] is not None, data
        importers = ["projects/tasks/epicollect.html",
                     "projects/tasks/csv.html",
                     "projects/tasks/s3.html",
                     "projects/tasks/twitter.html",
                     "projects/tasks/youtube.html",
                     "projects/tasks/gdocs.html",
                     "projects/tasks/dropbox.html",
                     "projects/tasks/flickr.html",
                     "projects/tasks/localCSV.html",
                     "projects/tasks/iiif.html"]
        assert sorted(data['available_importers']) == sorted(importers), (importers,
                                                          data['available_importers'])


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_get_import_tasks_no_params_shows_options_and_templates_json_user(self, mock):
        """Test WEB import tasks JSON returns tasks's templates """
        admin, user, owner = UserFactory.create_batch(3)
        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/tasks/import?api_key=%s' % (project.short_name, user.api_key)
        res = self.app_get_json(url)
        data = json.loads(res.data)
        assert data['code'] == 403, data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_get_import_tasks_no_params_shows_options_and_templates_json_anon(self, mock):
        """Test WEB import tasks JSON returns tasks's templates """
        admin, user, owner = UserFactory.create_batch(3)
        project = ProjectFactory.create(owner=owner)

        url = '/project/%s/tasks/import' % (project.short_name)
        res = self.app_get_json(url, follow_redirects=True)
        assert 'signin' in res.data, res.data


    @with_context
    def test_get_import_tasks_with_specific_variant_argument(self):
        """Test task importer with specific importer variant argument
        shows the form for it, for each of the variants"""
        self.register()
        self.signin()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(owner=owner)

        # CSV
        url = "/project/%s/tasks/import?type=csv" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From a CSV file" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # Google Docs
        url = "/project/%s/tasks/import?type=gdocs" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From a Google Docs Spreadsheet" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # Epicollect Plus
        url = "/project/%s/tasks/import?type=epicollect" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From an EpiCollect Plus project" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # Flickr
        url = "/project/%s/tasks/import?type=flickr" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From a Flickr Album" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # Dropbox
        url = "/project/%s/tasks/import?type=dropbox" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From your Dropbox account" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # Twitter
        url = "/project/%s/tasks/import?type=twitter" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From a Twitter hashtag or account" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # S3
        url = "/project/%s/tasks/import?type=s3" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From an Amazon S3 bucket" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # IIIF
        url = "/project/%s/tasks/import?type=iiif" % project.short_name
        res = self.app.get(url, follow_redirects=True)
        data = res.data.decode('utf-8')

        assert "From a IIIF manifest" in data
        assert 'action="/project/%E2%9C%93project1/tasks/import"' in data

        # Invalid
        url = "/project/%s/tasks/import?type=invalid" % project.short_name
        res = self.app.get(url, follow_redirects=True)

        assert res.status_code == 404, res.status_code

    @with_context
    @patch('pybossa.core.importer.get_all_importer_names')
    def test_get_importer_doesnt_show_unavailable_importers(self, names):
        names.return_value = ['csv', 'gdocs', 'epicollect', 's3']
        self.register()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(owner=owner)
        url = "/project/%s/tasks/import" % project.short_name

        res = self.app.get(url, follow_redirects=True)

        assert "type=flickr" not in res.data
        assert "type=dropbox" not in res.data
        assert "type=twitter" not in res.data

    @with_context
    @patch('pybossa.view.projects.redirect_content_type', wraps=redirect)
    @patch('pybossa.importers.csv.requests.get')
    def test_import_tasks_redirects_on_success(self, request, redirect):
        """Test WEB when importing tasks succeeds, user is redirected to tasks main page"""
        csv_file = FakeResponse(text='Foo,Bar,Baz\n1,2,3', status_code=200,
                                headers={'content-type': 'text/plain'},
                                encoding='utf-8')
        request.return_value = csv_file
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % project.short_name
        res = self.app.post(url, data={'csv_url': 'http://myfakecsvurl.com',
                                       'formtype': 'csv', 'form_name': 'csv'},
                            follow_redirects=True)

        assert "1 new task was imported successfully" in res.data
        redirect.assert_called_with('/project/%s/tasks/' % project.short_name)

    @with_context
    @patch('pybossa.view.projects.importer.count_tasks_to_import')
    @patch('pybossa.view.projects.importer.create_tasks')
    def test_import_few_tasks_is_done_synchronously(self, create, count):
        """Test WEB importing a small amount of tasks is done synchronously"""
        count.return_value = 1
        create.return_value = ImportReport(message='1 new task was imported successfully', metadata=None, total=1)
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % project.short_name
        res = self.app.post(url, data={'csv_url': 'http://myfakecsvurl.com',
                                       'formtype': 'csv', 'form_name': 'csv'},
                            follow_redirects=True)

        assert "1 new task was imported successfully" in res.data

    @with_context
    @patch('pybossa.view.projects.importer_queue', autospec=True)
    @patch('pybossa.view.projects.importer.count_tasks_to_import')
    def test_import_tasks_as_background_job(self, count_tasks, queue):
        """Test WEB importing a big amount of tasks is done in the background"""
        from pybossa.view.projects import MAX_NUM_SYNCHRONOUS_TASKS_IMPORT
        count_tasks.return_value = MAX_NUM_SYNCHRONOUS_TASKS_IMPORT + 1
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % project.short_name
        res = self.app.post(url, data={'csv_url': 'http://myfakecsvurl.com',
                                       'formtype': 'csv', 'form_name': 'csv'},
                            follow_redirects=True)
        tasks = db.session.query(Task).all()

        assert tasks == [], "Tasks should not be immediately added"
        data = {'type': 'csv', 'csv_url': 'http://myfakecsvurl.com'}
        queue.enqueue.assert_called_once_with(import_tasks, project.id, 'John Doe', **data)
        msg = "trying to import a large amount of tasks, so please be patient.\
            You will receive an email when the tasks are ready."
        print(res.data)
        assert msg in res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    @patch('pybossa.importers.csv.requests.get')
    def test_bulk_csv_import_works(self, Mock, mock):
        """Test WEB bulk import works"""
        csv_file = FakeResponse(text='Foo,Bar,priority_0\n1,2,3', status_code=200,
                                headers={'content-type': 'text/plain'},
                                encoding='utf-8')
        Mock.return_value = csv_file
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % (project.short_name)
        res = self.app.post(url, data={'csv_url': 'http://myfakecsvurl.com',
                                       'formtype': 'csv', 'form_name': 'csv'},
                            follow_redirects=True)
        task = db.session.query(Task).first()
        assert {u'Bar': u'2', u'Foo': u'1'} == task.info
        assert task.priority_0 == 3
        assert "1 new task was imported successfully" in res.data

        # Check that only new items are imported
        empty_file = FakeResponse(text='Foo,Bar,priority_0\n1,2,3\n4,5,6',
                                  status_code=200,
                                  headers={'content-type': 'text/plain'},
                                  encoding='utf-8')
        Mock.return_value = empty_file
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % (project.short_name)
        res = self.app.post(url, data={'csv_url': 'http://myfakecsvurl.com',
                                       'formtype': 'csv', 'form_name': 'csv'},
                            follow_redirects=True)
        project = db.session.query(Project).first()
        err_msg = "There should be only 2 tasks"
        assert len(project.tasks) == 2, (err_msg, project.tasks)
        n = 0
        csv_tasks = [{u'Foo': u'1', u'Bar': u'2'}, {u'Foo': u'4', u'Bar': u'5'}]
        for t in project.tasks:
            assert t.info == csv_tasks[n], "The task info should be the same"
            n += 1

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    @patch('pybossa.importers.csv.requests.get')
    @patch('pybossa.repositories.task_repository.ensure_task_assignment_to_project')
    def test_bulk_csv_import_error(self, ensure, Mock, mock):
        """Test WEB bulk import works"""
        ensure.side_effect = Exception('Task is missing data access level.')
        csv_file = FakeResponse(text='Foo,Bar,priority_0\n1,2,3', status_code=200,
                                headers={'content-type': 'text/plain'},
                                encoding='utf-8')
        Mock.return_value = csv_file
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % (project.short_name)
        res = self.app.post(url, data={'csv_url': 'http://myfakecsvurl.com',
                                    'formtype': 'csv', 'form_name': 'csv'},
                            follow_redirects=True)
        assert "1 task import failed due to Task is missing data access level" in res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    @patch('pybossa.importers.csv.requests.get')
    def test_bulk_gdocs_import_works(self, Mock, mock):
        """Test WEB bulk GDocs import works."""
        csv_file = FakeResponse(text='Foo,Bar,priority_0\n1,2,3', status_code=200,
                                headers={'content-type': 'text/plain'},
                                encoding='utf-8')
        Mock.return_value = csv_file
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % (project.short_name)
        res = self.app.post(url, data={'googledocs_url': 'http://drive.google.com',
                                       'formtype': 'gdocs', 'form_name': 'gdocs'},
                            follow_redirects=True)
        task = db.session.query(Task).first()
        assert {u'Bar': u'2', u'Foo': u'1'} == task.info
        assert task.priority_0 == 3
        assert "1 new task was imported successfully" in res.data

        # Check that only new items are imported
        empty_file = FakeResponse(text='Foo,Bar,priority_0\n1,2,3\n4,5,6',
                                  status_code=200,
                                  headers={'content-type': 'text/plain'},
                                  encoding='utf-8')
        Mock.return_value = empty_file
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % (project.short_name)
        res = self.app.post(url, data={'googledocs_url': 'http://drive.google.com',
                                       'formtype': 'gdocs', 'form_name': 'gdocs'},
                            follow_redirects=True)
        project = db.session.query(Project).first()
        assert len(project.tasks) == 2, "There should be only 2 tasks"
        n = 0
        csv_tasks = [{u'Foo': u'1', u'Bar': u'2'}, {u'Foo': u'4', u'Bar': u'5'}]
        for t in project.tasks:
            assert t.info == csv_tasks[n], "The task info should be the same"
            n += 1

        # Check that only new items are imported
        project = db.session.query(Project).first()
        url = '/project/%s/tasks/import' % (project.short_name)
        res = self.app.post(url, data={'googledocs_url': 'http://drive.google.com',
                                       'formtype': 'gdocs', 'form_name': 'gdocs'},
                            follow_redirects=True)
        project = db.session.query(Project).first()
        assert len(project.tasks) == 2, "There should be only 2 tasks"
        n = 0
        csv_tasks = [{u'Foo': u'1', u'Bar': u'2'}, {u'Foo': u'4', u'Bar': u'5'}]
        for t in project.tasks:
            assert t.info == csv_tasks[n], "The task info should be the same"
            n += 1
        assert "no new records" in res.data, res.data

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    @patch('pybossa.importers.epicollect.requests.get')
    def test_bulk_epicollect_import_works(self, Mock, mock):
        """Test WEB bulk Epicollect import works"""
        from pybossa.core import importer
        data = [dict(DeviceID=23)]
        fake_response = FakeResponse(text=json.dumps(data), status_code=200,
                                     headers={'content-type': 'application/json'},
                                     encoding='utf-8')
        Mock.return_value = fake_response
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        res = self.app.post(('/project/%s/tasks/import' % (project.short_name)),
                            data={'epicollect_project': 'fakeproject',
                                  'epicollect_form': 'fakeform',
                                  'formtype': 'json', 'form_name': 'epicollect'},
                            follow_redirects=True)

        project = db.session.query(Project).first()
        err_msg = "Tasks should be imported"
        assert "1 new task was imported successfully" in res.data, err_msg
        tasks = db.session.query(Task).filter_by(project_id=project.id).all()
        err_msg = "The imported task from EpiCollect is wrong"
        assert tasks[0].info['DeviceID'] == 23, err_msg

        data = [dict(DeviceID=23), dict(DeviceID=24)]
        fake_response = FakeResponse(text=json.dumps(data), status_code=200,
                                     headers={'content-type': 'application/json'},
                                     encoding='utf-8')
        Mock.return_value = fake_response
        res = self.app.post(('/project/%s/tasks/import' % (project.short_name)),
                            data={'epicollect_project': 'fakeproject',
                                  'epicollect_form': 'fakeform',
                                  'formtype': 'json', 'form_name': 'epicollect'},
                            follow_redirects=True)
        project = db.session.query(Project).first()
        assert len(project.tasks) == 2, "There should be only 2 tasks"
        n = 0
        epi_tasks = [{u'DeviceID': 23}, {u'DeviceID': 24}]
        for t in project.tasks:
            assert t.info == epi_tasks[n], "The task info should be the same"
            n += 1

    @with_context
    @patch('pybossa.importers.flickr.requests.get')
    def test_bulk_flickr_import_works(self, request):
        """Test WEB bulk Flickr import works"""
        data = {
            "photoset": {
                "id": "72157633923521788",
                "primary": "8947113500",
                "owner": "32985084@N00",
                "ownername": "Teleyinex",
                "photo": [{"id": "8947115130", "secret": "00e2301a0d",
                           "server": "5441", "farm": 6, "title": "Title",
                           "isprimary": 0, "ispublic": 1, "isfriend": 0,
                           "isfamily": 0}
                          ],
                "page": 1,
                "per_page": "500",
                "perpage": "500",
                "pages": 1,
                "total": 1,
                "title": "Science Hack Day Balloon Mapping Workshop"},
            "stat": "ok"}
        fake_response = FakeResponse(text=json.dumps(data), status_code=200,
                                     headers={'content-type': 'application/json'},
                                     encoding='utf-8')
        request.return_value = fake_response
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        res = self.app.post(('/project/%s/tasks/import' % (project.short_name)),
                            data={'album_id': '1234',
                                  'form_name': 'flickr'},
                            follow_redirects=True)

        project = db.session.query(Project).first()
        err_msg = "Tasks should be imported"
        assert "1 new task was imported successfully" in res.data, err_msg
        tasks = db.session.query(Task).filter_by(project_id=project.id).all()
        expected_info = {
            u'url': u'https://farm6.staticflickr.com/5441/8947115130_00e2301a0d.jpg',
            u'url_m': u'https://farm6.staticflickr.com/5441/8947115130_00e2301a0d_m.jpg',
            u'url_b': u'https://farm6.staticflickr.com/5441/8947115130_00e2301a0d_b.jpg',
            u'link': u'https://www.flickr.com/photos/32985084@N00/8947115130',
            u'title': u'Title'}
        assert tasks[0].info == expected_info, tasks[0].info

    @with_context
    def test_flickr_importer_page_shows_option_to_log_into_flickr(self):
        self.register()
        self.signin()
        owner = db.session.query(User).first()
        project = ProjectFactory.create(owner=owner)
        url = "/project/%s/tasks/import?type=flickr" % project.short_name

        res = self.app.get(url)
        login_url = '/flickr/?next=%2Fproject%2F%25E2%259C%2593project1%2Ftasks%2Fimport%3Ftype%3Dflickr'

        assert login_url in res.data

    @with_context
    def test_bulk_dropbox_import_works(self):
        """Test WEB bulk Dropbox import works"""
        dropbox_file_data = (u'{"bytes":286,'
                             u'"link":"https://www.dropbox.com/s/l2b77qvlrequ6gl/test.txt?dl=0",'
                             u'"name":"test.txt",'
                             u'"icon":"https://www.dropbox.com/static/images/icons64/page_white_text.png"}')
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        res = self.app.post('/project/%s/tasks/import' % project.short_name,
                            data={'files-0': dropbox_file_data,
                                  'form_name': 'dropbox'},
                            follow_redirects=True)

        project = db.session.query(Project).first()
        err_msg = "Tasks should be imported"
        tasks = db.session.query(Task).filter_by(project_id=project.id).all()
        expected_info = {
            u'link_raw': u'https://www.dropbox.com/s/l2b77qvlrequ6gl/test.txt?raw=1',
            u'link': u'https://www.dropbox.com/s/l2b77qvlrequ6gl/test.txt?dl=0',
            u'filename': u'test.txt'}
        assert tasks[0].info == expected_info, tasks[0].info

    @with_context
    @patch('pybossa.importers.twitterapi.Twitter')
    @patch('pybossa.importers.twitterapi.oauth2_dance')
    def test_bulk_twitter_import_works(self, oauth, client):
        """Test WEB bulk Twitter import works"""
        tweet_data = {
            'statuses': [
                {
                    u'created_at': 'created',
                    u'favorite_count': 77,
                    u'coordinates': 'coords',
                    u'id_str': u'1',
                    u'id': 1,
                    u'retweet_count': 44,
                    u'user': {'screen_name': 'fulanito'},
                    u'text': 'this is a tweet #match'
                }
            ]
        }
        client_instance = Mock()
        client_instance.search.tweets.return_value = tweet_data
        client.return_value = client_instance

        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        res = self.app.post('/project/%s/tasks/import' % project.short_name,
                            data={'source': '#match',
                                  'max_tweets': 1,
                                  'form_name': 'twitter'},
                            follow_redirects=True)

        project = db.session.query(Project).first()
        err_msg = "Tasks should be imported"
        tasks = db.session.query(Task).filter_by(project_id=project.id).all()
        expected_info = {
            u'created_at': 'created',
            u'favorite_count': 77,
            u'coordinates': 'coords',
            u'id_str': u'1',
            u'id': 1,
            u'retweet_count': 44,
            u'user': {'screen_name': 'fulanito'},
            u'user_screen_name': 'fulanito',
            u'text': 'this is a tweet #match'
        }
        assert tasks[0].info == expected_info, tasks[0].info

    @with_context
    def test_bulk_s3_import_works(self):
        """Test WEB bulk S3 import works"""
        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()
        res = self.app.post('/project/%s/tasks/import' % project.short_name,
                            data={'files-0': 'myfile.txt',
                                  'bucket': 'mybucket',
                                  'form_name': 's3'},
                            follow_redirects=True)

        project = db.session.query(Project).first()
        err_msg = "Tasks should be imported"
        tasks = db.session.query(Task).filter_by(project_id=project.id).all()
        expected_info = {
            u'url': u'https://mybucket.s3.amazonaws.com/myfile.txt',
            u'filename': u'myfile.txt',
            u'link': u'https://mybucket.s3.amazonaws.com/myfile.txt'
        }
        assert tasks[0].info == expected_info, tasks[0].info

    @with_context
    def test_55_facebook_account_warning(self):
        """Test WEB Facebook OAuth user gets a hint to sign in"""
        user = User(fullname='John',
                    name='john',
                    email_addr='john@john.com',
                    info={})

        user.info = dict(facebook_token=u'facebook')
        msg, method = get_user_signup_method(user)
        err_msg = "Should return 'facebook' but returned %s" % method
        assert method == 'facebook', err_msg

        user.info = dict(google_token=u'google')
        msg, method = get_user_signup_method(user)
        err_msg = "Should return 'google' but returned %s" % method
        assert method == 'google', err_msg

        user.info = dict(twitter_token=u'twitter')
        msg, method = get_user_signup_method(user)
        err_msg = "Should return 'twitter' but returned %s" % method
        assert method == 'twitter', err_msg

        user.info = {}
        msg, method = get_user_signup_method(user)
        err_msg = "Should return 'local' but returned %s" % method
        assert method == 'local', err_msg

    @with_context
    def test_56_delete_tasks(self):
        """Test WEB delete tasks works"""
        Fixtures.create()
        # Anonymous user
        res = self.app.get('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Anonymous user should be redirected for authentication"
        assert "This feature requires being logged in." in res.data, err_msg
        err_msg = "Anonymous user should not be allowed to delete tasks"
        res = self.app.post('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Anonymous user should not be allowed to delete tasks"
        assert "This feature requires being logged in." in res.data, err_msg

        # Authenticated user but not owner
        self.register()
        self.signin()
        res = self.app.get('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Authenticated user but not owner should get 403 FORBIDDEN in GET"
        assert res.status == '403 FORBIDDEN', err_msg
        res = self.app.post('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Authenticated user but not owner should get 403 FORBIDDEN in POST"
        assert res.status == '403 FORBIDDEN', err_msg
        self.signout()

        # Owner
        tasks = db.session.query(Task).filter_by(project_id=1).all()
        make_subadmin_by(email_addr=u'tester@tester.com')
        res = self.signin(email=u'tester@tester.com', password=u'tester')
        res = self.app.get('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Owner user should get 200 in GET"
        assert res.status == '200 OK', err_msg
        assert len(tasks) > 0, "len(project.tasks) > 0"
        res = self.app.post('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Owner should get 200 in POST"
        assert res.status == '200 OK', err_msg
        tasks = db.session.query(Task).filter_by(project_id=1).all()
        assert len(tasks) == 0, "len(project.tasks) != 0"

        # Admin
        res = self.signin(email=u'root@root.com', password=u'tester' + 'root')
        res = self.app.get('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Admin user should get 200 in GET"
        assert res.status_code == 200, err_msg
        res = self.app.post('/project/test-app/tasks/delete', follow_redirects=True)
        err_msg = "Admin should get 200 in POST"
        assert res.status_code == 200, err_msg

    @with_context
    def test_56_delete_tasks_json(self):
        """Test WEB delete tasks JSON works"""
        admin, owner, user = UserFactory.create_batch(3)
        make_subadmin(owner)
        project = ProjectFactory.create(owner=owner)
        TaskFactory.create(project=project)
        url = '/project/%s/tasks/delete' % project.short_name

        # Anonymous user
        res = self.app_get_json(url, follow_redirects=True)
        err_msg = "Anonymous user should be redirected for authentication"
        assert "This feature requires being logged in." in res.data, err_msg
        err_msg = "Anonymous user should not be allowed to delete tasks"
        res = self.app.post(url, follow_redirects=True)
        err_msg = "Anonymous user should not be allowed to delete tasks"
        assert "This feature requires being logged in." in res.data, err_msg

        # Authenticated user but not owner
        res = self.app_get_json(url + '?api_key=%s' % user.api_key)
        err_msg = "Authenticated user but not owner should get 403 FORBIDDEN in GET"
        assert res.status == '403 FORBIDDEN', err_msg
        res = self.app.post(url + '?api_key=%s' % user.api_key)
        err_msg = "Authenticated user but not owner should get 403 FORBIDDEN in POST"
        assert res.status == '403 FORBIDDEN', err_msg

        # Owner
        tasks = db.session.query(Task).filter_by(project_id=project.id).all()
        res = self.app_get_json(url + '?api_key=%s' % owner.api_key)
        err_msg = "Owner user should get 200 in GET"
        assert res.status == '200 OK', err_msg
        assert len(tasks) > 0, "len(project.tasks) > 0"
        res = self.app_post_json(url + '?api_key=%s' % owner.api_key)
        err_msg = "Owner should get 200 in POST"
        assert res.status == '200 OK', err_msg
        tasks = db.session.query(Task).filter_by(project_id=project.id).all()
        assert len(tasks) == 0, "len(project.tasks) != 0"

        # Admin
        res = self.app.get(url + '?api_key=%s' % admin.api_key)
        err_msg = "Admin user should get 200 in GET"
        assert res.status_code == 200, err_msg
        res = self.app_post_json(url + '?api_key=%s' % admin.api_key)
        err_msg = "Admin should get 200 in POST"
        assert res.status_code == 200, err_msg


    @with_context
    @patch('pybossa.repositories.task_repository.uploader')
    def test_delete_tasks_removes_existing_zip_files(self, uploader):
        """Test WEB delete tasks also deletes zip files for task and taskruns"""
        Fixtures.create()
        make_subadmin_by(email_addr=u'tester@tester.com')
        self.signin(email=u'tester@tester.com', password=u'tester')
        res = self.app.post('/project/test-app/tasks/delete', follow_redirects=True)
        expected = [call('1_test-app_task_json.zip', 'user_2'),
                    call('1_test-app_task_csv.zip', 'user_2'),
                    call('1_test-app_task_run_json.zip', 'user_2'),
                    call('1_test-app_task_run_csv.zip', 'user_2')]
        assert uploader.delete_file.call_args_list == expected

    @with_context
    def test_57_reset_api_key(self):
        """Test WEB reset api key works"""
        url = "/account/johndoe/update"
        # Anonymous user
        res = self.app.get(url, follow_redirects=True)
        err_msg = "Anonymous user should be redirected for authentication"
        assert "This feature requires being logged in." in res.data, err_msg
        res = self.app.post(url, follow_redirects=True)
        assert "This feature requires being logged in." in res.data, err_msg
        # Authenticated user
        self.register()
        self.signin()
        user = db.session.query(User).get(1)
        url = "/account/%s/update" % user.name
        api_key = user.api_key
        res = self.app.get(url, follow_redirects=True)
        err_msg = "Authenticated user should get access to reset api key page"
        assert res.status_code == 200, err_msg
        assert "reset your personal API Key" in res.data, err_msg
        url = "/account/%s/resetapikey" % user.name
        res = self.app.post(url, follow_redirects=True)
        err_msg = "Authenticated user should be able to reset his api key"
        assert res.status_code == 200, err_msg
        user = db.session.query(User).get(1)
        err_msg = "New generated API key should be different from old one"
        assert api_key != user.api_key, err_msg
        self.signout()

        self.register(fullname="new", name="new")
        self.signin(email="new@example.com", password="p4ssw0rd")
        res = self.app.post(url)
        assert res.status_code == 403, res.status_code

        url = "/account/fake/resetapikey"
        res = self.app.post(url)
        assert res.status_code == 404, res.status_code

    @with_context
    def test_57_reset_api_key_json(self):
        """Test WEB reset api key JSON works"""
        url = "/account/johndoe/update"
        # Anonymous user
        res = self.app_get_json(url, follow_redirects=True)
        err_msg = "Anonymous user should be redirected for authentication"
        assert "This feature requires being logged in." in res.data, err_msg
        res = self.app_post_json(url, data=dict(foo=1), follow_redirects=True)
        assert "This feature requires being logged in." in res.data, res.data
        # Authenticated user
        self.register()
        self.signin()
        user = db.session.query(User).get(1)
        url = "/account/%s/update" % user.name
        api_key = user.api_key
        res = self.app_get_json(url, follow_redirects=True)
        err_msg = "Authenticated user should get access to reset api key page"
        assert res.status_code == 200, err_msg
        data = json.loads(res.data)
        assert data.get('form').get('name') == user.name, (err_msg, data)

        with patch.dict(self.flask_app.config, {'WTF_CSRF_ENABLED': True}):
            url = "/account/%s/resetapikey" % user.name
            csrf = self.get_csrf(url)
            headers = {'X-CSRFToken': csrf}
            res = self.app_post_json(url,
                                     follow_redirects=True, headers=headers)
            err_msg = "Authenticated user should be able to reset his api key"
            assert res.status_code == 200, err_msg
            data = json.loads(res.data)
            assert data.get('status') == SUCCESS, err_msg
            assert data.get('next') == "/account/%s/" % user.name, (err_msg, data)
            user = db.session.query(User).get(1)
            err_msg = "New generated API key should be different from old one"
            assert api_key != user.api_key, (err_msg, data)
            self.signout()

            self.register(fullname="new", name="new")
            csrf = self.get_csrf('/account/signin')
            self.signin(email='new@example.com', csrf=csrf)
            res = self.app_post_json(url, headers=headers)
            assert res.status_code == 403, res.status_code
            data = json.loads(res.data)
            assert data.get('code') == 403, data

            url = "/account/fake/resetapikey"
            res = self.app_post_json(url, headers=headers)
            assert res.status_code == 404, res.status_code
            data = json.loads(res.data)
            assert data.get('code') == 404, data


    @with_context
    def test_58_global_stats(self):
        """Test WEB global stats of the site works"""
        Fixtures.create()
        user = user_repo.get(1)
        self.signin_user(user)

        url = "/stats"
        res = self.app.get(url, follow_redirects=True)
        err_msg = "There should be a Global Statistics page of the project"
        assert "General Statistics" in res.data, err_msg

    @with_context
    def test_58_global_stats_json(self):
        """Test WEB global stats JSON of the site works"""
        Fixtures.create()
        user = user_repo.get(1)
        self.signin_user(user)

        url = "/stats/"
        res = self.app_get_json(url)
        err_msg = "There should be a Global Statistics page of the project"
        data = json.loads(res.data)
        keys = ['projects', 'show_locs', 'stats', 'tasks', 'top5_projects_24_hours', 'top5_users_24_hours', 'users']
        assert keys.sort() == data.keys().sort(), keys


    @with_context
    def test_59_help_api(self):
        """Test WEB help api page exists"""
        Fixtures.create()
        url = "/help/api"
        res = self.app.get(url, follow_redirects=True)
        err_msg = "There should be a help api page"
        assert "API Help" in res.data, err_msg
        assert_raises(ValueError, json.loads, res.data)

    @with_context
    def test_59_help_api_json(self):
        """Test WEB help api json exists"""
        Fixtures.create()
        url = "/help/api"
        res = self.app_get_json(url, follow_redirects=True)
        data = json.loads(res.data)
        err_msg = 'Template wrong'
        assert data['template'] == 'help/api.html', err_msg
        err_msg = 'Title wrong'
        assert data['title'] == 'Help: API', err_msg
        err_msg = 'project id missing'
        assert 'project_id' in data, err_msg

    @with_context
    def test_59_help_license(self):
        """Test WEB help license page exists."""
        url = "/help/license"
        res = self.app.get(url, follow_redirects=True)
        err_msg = "There should be a help license page"
        assert "Licenses" in res.data, err_msg
        assert_raises(ValueError, json.loads, res.data)

    @with_context
    def test_59_help_license_json(self):
        """Test WEB help license json exists."""
        url = "/help/license"
        res = self.app_get_json(url, follow_redirects=True)
        data = json.loads(res.data)
        err_msg = 'Template wrong'
        assert data['template'] == 'help/license.html', err_msg
        err_msg = 'Title wrong'
        assert data['title'] == 'Help: Licenses', err_msg

    @with_context
    def test_59_about(self):
        """Test WEB help about page exists."""
        url = "/about"
        res = self.app.get(url, follow_redirects=True)
        err_msg = "There should be an about page"
        assert "About" in res.data, err_msg

    @with_context
    def test_59_help_tos(self):
        """Test WEB help TOS page exists."""
        url = "/help/terms-of-use"
        res = self.app.get(url, follow_redirects=True)
        err_msg = "There should be a TOS page"
        assert "Terms for use" in res.data, err_msg
        assert_raises(ValueError, json.loads, res.data)

    @with_context
    def test_59_help_tos_json(self):
        """Test WEB help TOS json endpoint exists"""
        url = "/help/terms-of-use"
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = 'Template wrong'
        assert data['template'] == 'help/tos.html', err_msg
        err_msg = 'Title wrong'
        assert data['title'] == 'Help: Terms of Use', err_msg
        err_msg = "There should be HTML content"
        assert '<body' in data['content'], err_msg

    @with_context
    def test_59_help_cookies_policy(self):
        """Test WEB help cookies policy page exists."""
        url = "/help/cookies-policy"
        res = self.app.get(url, follow_redirects=True)
        err_msg = "There should be a TOS page"
        assert "uses cookies" in res.data, err_msg
        assert_raises(ValueError, json.loads, res.data)

    @with_context
    def test_59_help_cookies_policy_json(self):
        """Test WEB help cookies policy json endpoint exists."""
        url = "/help/cookies-policy"
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = 'Template wrong'
        assert data['template'] == 'help/cookies_policy.html', err_msg
        err_msg = 'Title wrong'
        assert data['title'] == 'Help: Cookies Policy', err_msg
        err_msg = "There should be HTML content"
        assert '<body' in data['content'], err_msg

    @with_context
    def test_59_help_privacy(self):
        """Test WEB help privacy page exists."""
        self.signin_user()
        url = "/help/privacy"
        res = self.app.get(url, follow_redirects=True)
        err_msg = "There should be a privacy policy page"
        assert "Privacy" in res.data, err_msg
        assert_raises(ValueError, json.loads, res.data)

    @with_context
    def test_60_help_privacy_json(self):
        """Test privacy json endpoint"""
        self.signin_user()
        url = "/help/privacy"
        res = self.app_get_json(url)
        data = json.loads(res.data)
        err_msg = 'Template wrong'
        assert data['template'] == 'help/privacy.html', err_msg
        err_msg = 'Title wrong'
        assert data['title'] == 'Privacy Policy', err_msg
        err_msg = "There should be HTML content"
        assert '<body' in data['content'], err_msg

    @with_context
    def test_69_allow_anonymous_contributors(self):
        """Test WEB allow anonymous contributors works"""
        Fixtures.create()
        project = db.session.query(Project).first()
        url = '/project/%s/newtask' % project.short_name

        # All users are allowed to participate by default
        # As Anonymous user
        #res = self.app.get(url, follow_redirects=True)
        #err_msg = "The anonymous user should be able to participate"
        #assert project.name in res.data, err_msg

        # As registered user
        self.register()
        self.signin()
        res = self.app.get(url, follow_redirects=True)
        err_msg = "The anonymous user should be able to participate"
        assert project.name in res.data, err_msg
        self.signout()

        # Now only allow authenticated users
        project.allow_anonymous_contributors = False
        db.session.add(project)
        db.session.commit()

        # As Anonymous user
        res = self.app.get(url, follow_redirects=True)
        err_msg = "User should be redirected to sign in"
        project = db.session.query(Project).first()
        msg = "This feature requires being logged in"
        assert msg in res.data, err_msg

        # As registered user
        res = self.signin()
        res = self.app.get(url, follow_redirects=True)
        err_msg = "The authenticated user should be able to participate"
        assert project.name in res.data, err_msg
        self.signout()

        # Now only allow authenticated users
        project.allow_anonymous_contributors = False
        db.session.add(project)
        db.session.commit()
        res = self.app.get(url, follow_redirects=True)
        err_msg = "Only authenticated users can participate"
        assert 'This feature requires being logged in' in res.data, err_msg

    @with_context
    def test_70_public_user_profile(self):
        """Test WEB public user profile works"""
        Fixtures.create()

        # Should not work as an anonymous user
        url = '/account/%s/' % Fixtures.name
        res = self.app.get(url, follow_redirects=True)
        err_msg = "Profile requires being logged in"
        assert 'This feature requires being logged in.' in res.data, err_msg

        # Should work as an authenticated user
        user = user_repo.get(2)
        self.signin_user(user)
        res = self.app.get(url, follow_redirects=True)
        assert Fixtures.fullname in res.data, err_msg

        # Should return 404 when a user does not exist
        url = '/account/a-fake-name-that-does-not-exist/'
        res = self.app.get(url, follow_redirects=True)
        err_msg = "It should return a 404"
        assert res.status_code == 404, err_msg

    @with_context
    def test_71_public_user_profile_json(self):
        """Test JSON WEB public user profile works"""

        res = self.app.get('/account/nonexistent/',
                           content_type='application/json')
        assert res.status_code == 302, res.status_code

        Fixtures.create()

        # Should not work as an anonymous user
        url = '/account/%s/' % Fixtures.name
        res = self.app.get(url, content_type='application/json')
        assert res.status_code == 302, res.status_code

        self.signin_user(id=4)
        res = self.app.get(url, content_type='application/json')
        assert res.status_code == 200, res.status_code
        data = json.loads(res.data)
        err_msg = 'there should be a title for the user page'
        assert data['title'] == 'T Tester &middot; User Profile', err_msg
        err_msg = 'there should be a user name'
        assert data['user']['name'] == 'tester', err_msg
        err_msg = 'there should not be a user id'
        assert 'id' not in data['user'], err_msg

    @with_context
    def test_72_profile_url_json(self):
        """Test JSON WEB public user profile works"""

        res = self.app.get('/account/profile',
                           content_type='application/json')
        # should redirect to login
        assert res.status_code == 302, res.status_code

    @with_context
    def test_72_profile_url_json_restrict(self):
        """Test JSON WEB public user profile restrict works"""

        user = UserFactory.create(restrict=True)
        admin = UserFactory.create(admin=True)
        other = UserFactory.create()

        url = '/account/profile?api_key=%s' % user.api_key

        res = self.app.get(url,
                           content_type='application/json')
        assert res.status_code == 200, res.status_code
        data = json.loads(res.data)
        assert data.get('user') is not None, data
        userDict = data.get('user')
        assert userDict['id'] == user.id, userDict
        assert userDict['restrict'] is True, userDict

        # As admin should return nothing
        url = '/account/%s/?api_key=%s' % (user.name, admin.api_key)

        res = self.app.get(url, content_type='application/json')
        assert res.status_code == 200, res.status_code
        data = json.loads(res.data)
        assert data.get('user') is None, data
        assert data.get('title') == 'User data is restricted'
        assert data.get('can_update') is True
        assert data.get('projects_created') == []
        assert data.get('projects') == [], data

        # As another user should return nothing
        url = '/account/%s/?api_key=%s' % (user.name, other.api_key)

        res = self.app.get(url,
                           content_type='application/json')
        assert res.status_code == 200, res.status_code
        data = json.loads(res.data)
        assert data.get('user') is None, data
        assert data.get('title') == 'User data is restricted'
        assert data.get('can_update') is False
        assert data.get('projects_created') == []
        assert data.get('projects') == [], data



    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_74_task_settings_page(self, mock):
        """Test WEB TASK SETTINGS page works"""
        # Creat root user
        self.register()
        self.signout()
        # As owner
        self.register()
        self.signin()
        res = self.new_project()
        url = "/project/sampleapp/tasks/settings"

        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        divs = ['task_scheduler', 'task_delete', 'task_redundancy']
        for div in divs:
            err_msg = "There should be a %s section" % div
            assert dom.find(id=div) is not None, err_msg

        self.signout()
        # As an authenticated user
        self.register(fullname="juan", name="juan")
        self.signin(email="juan@example.com", password="p4ssw0rd")
        res = self.app.get(url, follow_redirects=True)
        err_msg = "User should not be allowed to access this page"
        assert res.status_code == 403, err_msg
        self.signout()

        # As an anonymous user
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "User should be redirected to sign in"
        assert dom.find(id="signin") is not None, err_msg

        # As root
        self.signin()
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        divs = ['task_scheduler', 'task_delete', 'task_redundancy']
        for div in divs:
            err_msg = "There should be a %s section" % div
            assert dom.find(id=div) is not None, err_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_75_task_settings_scheduler(self, mock):
        """Test WEB TASK SETTINGS scheduler page works"""
        # Creat root user
        self.register()
        self.signout()
        # Create owner
        self.register()
        self.signin()
        self.new_project()
        url = "/project/sampleapp/tasks/scheduler"
        form_id = 'task_scheduler'
        self.signout()

        # As owner and root
        for i in range(0, 1):
            if i == 0:
                self.signin()
                sched = 'depth_first'
            else:
                sched = 'default'
                self.signin()
            res = self.app.get(url, follow_redirects=True)
            dom = BeautifulSoup(res.data)
            err_msg = "There should be a %s section" % form_id
            assert dom.find(id=form_id) is not None, err_msg
            res = self.task_settings_scheduler(short_name="sampleapp",
                                               sched=sched)
            err_msg = "Task Scheduler should be updated"
            assert "Project Task Scheduler updated" in res.data, err_msg
            assert "success" in res.data, err_msg
            project = db.session.query(Project).get(1)
            assert project.info['sched'] == sched, err_msg
            self.signout()

        # As an authenticated user
        self.register(fullname="juan", name="juan")
        self.signin(email="juan@example.com", password="p4ssw0rd")
        res = self.app.get(url, follow_redirects=True)
        err_msg = "User should not be allowed to access this page"
        assert res.status_code == 403, err_msg
        self.signout()

        # As an anonymous user
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "User should be redirected to sign in"
        assert dom.find(id="signin") is not None, err_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_75_available_task_schedulers(self, mock):
        """Test WEB TASK SETTINGS scheduler page works"""
        # Creat root user
        self.register()
        self.signin()
        self.new_project()
        url = "/project/sampleapp/tasks/scheduler"
        form_id = 'task_scheduler'
        from pybossa.core import setup_schedulers

        try:
            sched_config = [
                ('default', 'Default'),
                ('locked_scheduler', 'Locked Scheduler')
            ]
            with patch.dict(self.flask_app.config, {'AVAILABLE_SCHEDULERS': sched_config}):
                setup_schedulers(self.flask_app)

            res = self.app.get(url, follow_redirects=True)
            dom = BeautifulSoup(res.data)
            form = dom.find(id=form_id)
            assert form is not None, res.data
            options = dom.find_all('option')
            assert len(options) == len(sched_config)
            scheds = [o.attrs['value'] for o in options]
            assert all(s in scheds for s, d in sched_config)
        finally:
            from pybossa.sched import sched_variants
            sched_config = sched_variants()
            with patch.dict(self.flask_app.config, {'AVAILABLE_SCHEDULERS': sched_config}):
                setup_schedulers(self.flask_app)

        # all schedulers
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        form = dom.find(id=form_id)
        assert form is not None, err_msg
        options = dom.find_all('option')
        scheds = [o.attrs['value'] for o in options]
        assert 'user_pref_scheduler' in scheds
        assert 'breadth_first' in scheds

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_75_task_settings_scheduler_json(self, mock):
        """Test WEB TASK SETTINGS JSON scheduler page works"""
        admin, owner, user = UserFactory.create_batch(3)
        make_subadmin(owner)
        project = ProjectFactory.create(owner=owner)
        url = "/project/%s/tasks/scheduler" % project.short_name
        form_id = 'task_scheduler'

        # As owner and root
        for i in range(0, 1):
            if i == 0:
                # As owner
                new_url = url + '?api_key=%s' % owner.api_key
                sched = 'depth_first'
            else:
                new_url = url + '?api_key=%s' % admin.api_key
                sched = 'default'
            res = self.app_get_json(new_url)
            data = json.loads(res.data)
            assert data['form']['csrf'] is not None, data
            assert 'sched' in data['form'].keys(), data

            res = self.app_post_json(new_url, data=dict(sched=sched))
            data = json.loads(res.data)
            project = db.session.query(Project).get(1)
            assert project.info['sched'] == sched, err_msg
            assert data['status'] == SUCCESS, data

        # As an authenticated user
        res = self.app_get_json(url + '?api_key=%s' % user.api_key)
        err_msg = "User should not be allowed to access this page"
        assert res.status_code == 403, err_msg

        # As an anonymous user
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "User should be redirected to sign in"
        assert dom.find(id="signin") is not None, err_msg


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_76_task_settings_redundancy(self, mock):
        """Test WEB TASK SETTINGS redundancy page works"""
        # Creat root user
        self.register()
        self.signout()
        # Create owner
        self.register()
        self.signin()
        self.new_project()
        self.new_task(1)

        url = "/project/sampleapp/tasks/redundancy"
        form_id = 'task_redundancy'
        self.signout()

        # As owner and root
        for i in range(0, 1):
            if i == 0:
                # As owner
                self.signin()
                n_answers = 20
            else:
                n_answers = 10
                self.signin()
            res = self.app.get(url, follow_redirects=True)
            dom = BeautifulSoup(res.data)
            # Correct values
            err_msg = "There should be a %s section" % form_id
            assert dom.find(id=form_id) is not None, err_msg
            res = self.task_settings_redundancy(short_name="sampleapp",
                                                n_answers=n_answers)
            db.session.close()
            err_msg = "Task Redundancy should be updated"
            assert "Redundancy updated!" in res.data, err_msg
            assert "success" in res.data, err_msg
            project = db.session.query(Project).get(1)
            for t in project.tasks:
                assert t.n_answers == n_answers, err_msg
            # Wrong values, triggering the validators
            res = self.task_settings_redundancy(short_name="sampleapp",
                                                n_answers=0)
            err_msg = "Task Redundancy should be a value between 0 and 1000"
            assert "error" in res.data, err_msg
            assert "success" not in res.data, err_msg
            res = self.task_settings_redundancy(short_name="sampleapp",
                                                n_answers=10000000)
            err_msg = "Task Redundancy should be a value between 0 and 1000"
            assert "error" in res.data, err_msg
            assert "success" not in res.data, err_msg

            self.signout()

        # As an authenticated user
        self.register(fullname="juan", name="juan")
        self.signin(email="juan@example.com")
        res = self.app.get(url, follow_redirects=True)
        err_msg = "User should not be allowed to access this page"
        assert res.status_code == 403, err_msg
        self.signout()

        # As an anonymous user
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "User should be redirected to sign in"
        assert dom.find(id="signin") is not None, err_msg


    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_76_task_settings_redundancy_json(self, mock):
        """Test WEB TASK SETTINGS redundancy JSON page works"""
        admin, owner, user = UserFactory.create_batch(3)
        make_subadmin(owner)
        project = ProjectFactory.create(owner=owner)

        url = "/project/%s/tasks/redundancy" % project.short_name
        form_id = 'task_redundancy'

        # As owner and root
        for i in range(0, 1):
            if i == 0:
                # As owner
                new_url = url + '?api_key=%s' % owner.api_key
                self.signin(email="owner@example.com")
                n_answers = 20
            else:
                new_url = url + '?api_key=%s' % admin.api_key
                n_answers = 10
                self.signin()
            res = self.app_get_json(new_url)
            data = json.loads(res.data)
            assert data['form']['csrf'] is not None, data
            assert 'n_answers' in data['form'].keys(), data

            res = self.app_post_json(new_url, data=dict(n_answers=n_answers))
            data = json.loads(res.data)
            assert data['status'] == SUCCESS, data
            project = db.session.query(Project).get(1)
            for t in project.tasks:
                assert t.n_answers == n_answers, err_msg

            res = self.app_post_json(new_url, data=dict(n_answers=-1))
            data = json.loads(res.data)
            err_msg = "Task Redundancy should be a value between 1 and 1000"
            assert data['status'] == 'error', data
            assert 'between 1 and 1,000' in data['form']['errors']['n_answers'][0], data

            res = self.app_post_json(new_url, data=dict(n_answers=10000000000))
            data = json.loads(res.data)
            err_msg = "Task Redundancy should be a value between 1 and 1000"
            assert data['status'] == 'error', data
            assert 'between 1 and 1,000' in data['form']['errors']['n_answers'][0], err_msg

        # As an authenticated user
        res = self.app_get_json(url + '?api_key=%s' % user.api_key)
        err_msg = "User should not be allowed to access this page"
        assert res.status_code == 403, err_msg

        # As an anonymous user
        res = self.app_get_json(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "User should be redirected to sign in"
        assert dom.find(id="signin") is not None, err_msg


    @with_context
    def test_task_redundancy_update_updates_task_state(self):
        """Test WEB when updating the redundancy of the tasks in a project, the
        state of the task is updated in consecuence"""
        # Creat root user
        self.register()
        self.signin()
        self.new_project()
        self.new_task(1)

        url = "/project/sampleapp/tasks/redundancy"

        project = db.session.query(Project).get(1)
        for t in project.tasks:
            tr = TaskRun(project_id=project.id, task_id=t.id)
            db.session.add(tr)
            db.session.commit()

        err_msg = "Task state should be completed"
        res = self.task_settings_redundancy(short_name="sampleapp",
                                            n_answers=1)

        for t in project.tasks:
            assert t.state == 'completed', err_msg

        res = self.task_settings_redundancy(short_name="sampleapp",
                                            n_answers=2)
        err_msg = "Task state should be ongoing"
        db.session.add(project)
        db.session.commit()

        for t in project.tasks:
            assert t.state == 'ongoing', t.state

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_77_task_settings_priority(self, mock):
        """Test WEB TASK SETTINGS priority page works"""
        # Creat root user
        self.register()
        self.signin()
        self.new_project()
        self.new_task(1)
        url = "/project/sampleapp/tasks/priority"
        form_id = 'task_priority'

        # As owner and root
        project = db.session.query(Project).get(1)
        _id = project.tasks[0].id
        for i in range(0, 1):
            if i == 0:
                task_ids = str(_id)
                priority_0 = 1.0
            else:
                task_ids = "1"
                priority_0 = 0.5
            res = self.app.get(url, follow_redirects=True)
            dom = BeautifulSoup(res.data)
            # Correct values
            err_msg = "There should be a %s section" % form_id
            assert dom.find(id=form_id) is not None, err_msg
            res = self.task_settings_priority(short_name="sampleapp",
                                              task_ids=task_ids,
                                              priority_0=priority_0)
            err_msg = "Task Priority should be updated"
            assert "error" not in res.data, err_msg
            assert "success" in res.data, err_msg
            task = db.session.query(Task).get(_id)
            assert task.id == int(task_ids), err_msg
            assert task.priority_0 == priority_0, err_msg
            # Wrong values, triggering the validators
            res = self.task_settings_priority(short_name="sampleapp",
                                              priority_0=3,
                                              task_ids="1")
            err_msg = "Task Priority should be a value between 0.0 and 1.0"
            assert "error" in res.data, err_msg
            assert "success" not in res.data, err_msg
            res = self.task_settings_priority(short_name="sampleapp",
                                              task_ids="1, 2")
            err_msg = "Task Priority task_ids should be a comma separated, no spaces, integers"
            assert "error" in res.data, err_msg
            assert "success" not in res.data, err_msg
            res = self.task_settings_priority(short_name="sampleapp",
                                              task_ids="1,a")
            err_msg = "Task Priority task_ids should be a comma separated, no spaces, integers"
            assert "error" in res.data, err_msg
            assert "success" not in res.data, err_msg

            self.signout()

        # As an authenticated user
        self.register(fullname="juan", name="juan")
        self.signin(email="juan@example.com")
        res = self.app.get(url, follow_redirects=True)
        err_msg = "User should not be allowed to access this page"
        assert res.status_code == 403, err_msg
        self.signout()

        # As an anonymous user
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "User should be redirected to sign in"
        assert dom.find(id="signin") is not None, err_msg

    @with_context
    @patch('pybossa.view.projects.uploader.upload_file', return_value=True)
    def test_77_task_settings_priority_json(self, mock):
        """Test WEB TASK SETTINGS JSON priority page works"""
        admin, owner, user = UserFactory.create_batch(3)
        project = ProjectFactory.create(owner=owner)
        TaskFactory.create(project=project)
        url = "/project/%s/tasks/priority" % project.short_name
        form_id = 'task_priority'

        # As owner and root
        project = db.session.query(Project).get(project.id)
        _id = project.tasks[0].id
        for i in range(0, 1):
            if i == 0:
                # As owner
                new_url = url + '?api_key=%s' % owner.api_key
                task_ids = str(_id)
                priority_0 = 1.0
            else:
                new_url = url + '?api_key=%s' % admin.api_key
                task_ids = "1"
                priority_0 = 0.5
            res = self.app_get_json(new_url)
            assert res.status_code == 403, 'non subadminowner cannot do it'
            make_subadmin(owner)

            res = self.app_get_json(new_url)
            data = json.loads(res.data)
            assert data['form']['csrf'] is not None, data
            assert 'priority_0' in data['form'].keys(), data
            assert 'task_ids' in data['form'].keys(), data
            res = self.app_post_json(new_url, data=dict(task_ids=task_ids,
                                                        priority_0=priority_0))
            data = json.loads(res.data)
            assert data['status'] == SUCCESS, data

            err_msg = "Priority should be changed."
            task = db.session.query(Task).get(_id)
            assert task.id == int(task_ids), err_msg
            assert task.priority_0 == priority_0, err_msg
            # Wrong values, triggering the validators
            res = self.app_post_json(new_url, data=dict(priority_0=3, task_ids="1"))
            data = json.loads(res.data)
            assert data['status'] == 'error', data
            assert len(data['form']['errors']['priority_0']) == 1, data


            res = self.app_post_json(new_url, data=dict(priority_0=3, task_ids="1, 2"))
            data = json.loads(res.data)
            assert data['status'] == 'error', data
            assert len(data['form']['errors']['task_ids']) == 1, data

            res = self.app_post_json(new_url, data=dict(priority_0=3, task_ids="1, a"))
            data = json.loads(res.data)
            assert data['status'] == 'error', data
            assert len(data['form']['errors']['task_ids']) == 1, data


        # As an authenticated user
        res = self.app.get(url + '?api_key=%s' % user.api_key)
        err_msg = "User should not be allowed to access this page"
        assert res.status_code == 403, err_msg

        # As an anonymous user
        res = self.app.get(url, follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "User should be redirected to sign in"
        assert dom.find(id="signin") is not None, err_msg

    @with_context
    def test_task_gold_not_login(self):
        """Test WEB when making a task gold without auth"""
        url = "/api/project/1/taskgold"
        project = project_repo.get(1)
        payload = {'info': {'ans1': 'test'}, 'task_id': 1, 'project_id': 1}

        res = self.app_post_json(url,
                            data=payload,
                            follow_redirects=False,
                            )

        data = json.loads(res.data)
        assert data.get('status_code') == 401, data

    @with_context
    def test_task_gold_wrong_project_id(self):
        """Test WEB when making a task gold with wrong project id"""
        url = "/api/project/3/taskgold"
        project = project_repo.get(1)
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')
        self.new_project()
        self.new_task(1)

        wrong_payload = {'info': {'ans1': 'test'}, 'task_id': 1, 'project_id': 2}
        res = self.app_post_json(url,
                            data=wrong_payload,
                            follow_redirects=False,
                            )

        data = json.loads(res.data)
        assert data.get('status_code') == 403, data

    @with_context
    def test_task_gold_no_admin_or_owner(self):
        """Test WEB when making a task gold as a unauthorized user"""
        url = "/api/project/1/taskgold"
        user = UserFactory.create()
        user.set_password('1234')
        user_repo.save(user)
        self.signin(email=user.email_addr, password='1234')

        payload = {'info': {'ans1': 'test'}, 'task_id': 1, 'project_id': 1}
        res = self.app_post_json(url,
                            data=payload,
                            follow_redirects=False,
                            )

        data = json.loads(res.data)
        assert data.get('status_code') == 403, data

    @with_context
    def test_task_gold(self):
        """Test WEB when making a task gold"""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')
        self.new_project()
        self.new_task(1)


        url = "/api/project/1/taskgold"

        project = project_repo.get(1)

        payload = {'info': {'ans1': 'test'}, 'task_id': 1, 'project_id': 1}
        res = self.app_post_json(url,
                            data=payload,
                            follow_redirects=False,
                            )

        data = json.loads(res.data)
        assert data.get('success') == True, data

        t = task_repo.get_task(1)

        assert t.state == 'ongoing', t.state
        assert t.calibration == 1, t.calibration
        assert t.exported == True, t.exported
        assert t.gold_answers == {'ans1': 'test'}, t.gold_answers



    @with_context
    @patch('pybossa.api.task.url_for', return_value='testURL')
    @patch('pybossa.api.task.upload_json_data')
    def test_task_gold_priv(self, mock, mock2):
        """Test WEB when making a task gold for priv"""
        from pybossa.view.projects import data_access_levels

        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(info={
                'data_access': ["L1"],
                'ext_config': {'data_access': {'tracking_id': '123'}}
            })
        task = Task(project_id=project.id, info={'data_access': ['L1']})
        task_repo.save(task)

        url = "/api/project/1/taskgold"

        payload = {'info': {'ans1': 'test'}, 'task_id': 1, 'project_id': 1}

        with patch.dict(data_access_levels, self.patch_data_access_levels):
            res = self.app_post_json(url,
                                data=payload,
                                follow_redirects=False,
                                )

            data = json.loads(res.data)
            assert data.get('success') == True, data

            t = task_repo.get_task(1)

            assert t.state == 'ongoing', t.state
            assert t.calibration == 1, t.calibration
            assert t.exported == True, t.exported
            assert t.gold_answers == 'testURL', t.gold_answers



    @with_context
    def test_78_cookies_warning(self):
        """Test WEB cookies warning is displayed"""
        # As Anonymous
        res = self.app.get('/', follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "If cookies are not accepted, cookies banner should be shown"
        assert dom.find(id='cookies_warning') is not None, err_msg

        # As user
        self.signin(email=Fixtures.email_addr2, password=Fixtures.password)
        res = self.app.get('/', follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "If cookies are not accepted, cookies banner should be shown"
        assert dom.find(id='cookies_warning') is not None, err_msg
        self.signout()

        # As admin
        self.signin(email=Fixtures.root_addr, password=Fixtures.root_password)
        res = self.app.get('/', follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "If cookies are not accepted, cookies banner should be shown"
        assert dom.find(id='cookies_warning') is not None, err_msg
        self.signout()

    @with_context
    def test_79_cookies_warning2(self):
        """Test WEB cookies warning is hidden"""
        # As Anonymous
        self.app.set_cookie("localhost", "cookieconsent_dismissed", "Yes")
        res = self.app.get('/', follow_redirects=True, headers={})
        dom = BeautifulSoup(res.data)
        err_msg = "If cookies are not accepted, cookies banner should be hidden"
        assert dom.find('div', attrs={'class': 'cc_banner-wrapper'}) is None, err_msg

        # As user
        self.signin(email=Fixtures.email_addr2, password=Fixtures.password)
        res = self.app.get('/', follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "If cookies are not accepted, cookies banner should be hidden"
        assert dom.find('div', attrs={'class': 'cc_banner-wrapper'}) is None, err_msg
        self.signout()

        # As admin
        self.signin(email=Fixtures.root_addr, password=Fixtures.root_password)
        res = self.app.get('/', follow_redirects=True)
        dom = BeautifulSoup(res.data)
        err_msg = "If cookies are not accepted, cookies banner should be hidden"
        assert dom.find('div', attrs={'class': 'cc_banner-wrapper'}) is None, err_msg
        self.signout()

    @with_context
    def test_user_with_no_more_tasks_find_volunteers(self):
        """Test WEB when a user has contributed to all available tasks, he is
        asked to find new volunteers for a project, if the project is not
        completed yet (overall progress < 100%)"""

        self.register()
        self.signin()
        user = User.query.first()
        project = ProjectFactory.create(owner=user)
        task = TaskFactory.create(project=project)
        taskrun = TaskRunFactory.create(task=task, user=user)
        res = self.app.get('/project/%s/newtask' % project.short_name)

        message = "Sorry, you've contributed to all the tasks for this project, but this project still needs more volunteers, so please spread the word!"
        assert message in res.data
        self.signout()

    @with_context
    def test_user_with_no_more_tasks_find_volunteers_project_completed(self):
        """Test WEB when a user has contributed to all available tasks, he is
        not asked to find new volunteers for a project, if the project is
        completed (overall progress = 100%)"""

        self.register()
        self.signin()
        user = User.query.first()
        project = ProjectFactory.create(owner=user)
        task = TaskFactory.create(project=project, n_answers=1)
        taskrun = TaskRunFactory.create(task=task, user=user)
        update_stats(project.id)
        res = self.app.get('/project/%s/newtask' % project.short_name)

        assert task.state == 'completed', task.state
        message = "Sorry, you've contributed to all the tasks for this project, but this project still needs more volunteers, so please spread the word!"
        assert message not in res.data
        self.signout()

    @with_context
    def test_update_project_secret_key_owner(self):
        """Test update project secret key owner."""
        self.register()
        self.signin()
        self.new_project()

        project = project_repo.get(1)

        old_key = project.secret_key

        url = "/project/%s/resetsecretkey" % project.short_name

        res = self.app.post(url, follow_redirects=True)

        project = project_repo.get(1)

        err_msg = "A new key should be generated"
        assert "New secret key generated" in res.data, err_msg
        assert old_key != project.secret_key, err_msg

    @with_context
    def test_update_project_secret_key_owner_json(self):
        """Test update project secret key owner."""
        self.register()
        self.signin()
        self.new_project()

        project = project_repo.get(1)

        old_key = project.secret_key

        csrf_url = "/project/%s/update" % project.short_name
        url = "/project/%s/resetsecretkey" % project.short_name

        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        res = self.app_post_json(url, headers={'X-CSRFToken': csrf})
        data = json.loads(res.data)
        assert data['flash'] == 'New secret key generated', data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'success', data

        project = project_repo.get(1)

        err_msg = "A new key should be generated"
        assert "New secret key generated" in res.data, err_msg
        assert old_key != project.secret_key, err_msg


    @with_context
    def test_update_project_secret_key_not_owner(self):
        """Test update project secret key not owner."""
        self.register()
        self.signin()
        self.new_project()
        self.signout()

        self.register(email="juan@juan.com", name="juanjuan")

        self.signin(email="juan@juan.com", password="p4ssw0rd")
        project = project_repo.get(1)

        url = "/project/%s/resetsecretkey" % project.short_name

        res = self.app.post(url, follow_redirects=True)

        assert res.status_code == 403, res.status_code

    @with_context
    def test_update_project_secret_key_not_owner_json(self):
        """Test update project secret key not owner."""
        self.register()
        self.signin()
        self.new_project()
        self.signout()

        self.register(email="juan@juan.com", name="juanjuan")
        self.signin(email="juan@juan.com", password="p4ssw0rd")

        project = project_repo.get(1)

        url = "/project/%s/resetsecretkey" % project.short_name

        res = self.app_post_json(url)

        assert res.status_code == 403, res.status_code

    @patch('pybossa.view.account.mail_queue')
    @patch('pybossa.otp.OtpAuth')
    @with_context_settings(ENABLE_TWO_FACTOR_AUTH=True)
    def test_otp_signin_signout_json(self, OtpAuth, mail_queue):
        """Test WEB two factor sign in and sign out JSON works"""
        self.register()
        # Log out as the registration already logs in the user
        self.signout()

        res = self.signin(method="GET", content_type="application/json",
                          follow_redirects=False)
        data = json.loads(res.data)
        err_msg = "There should be a form with two keys email & password"
        csrf = data['form'].get('csrf')
        assert data.get('title') == "Sign in", data
        assert 'email' in data.get('form').keys(), (err_msg, data)
        assert 'password' in data.get('form').keys(), (err_msg, data)

        OTP = '1234'
        otp_secret = OtpAuth.return_value
        otp_secret.totp.return_value = OTP

        res = self.signin(content_type="application/json",
                          csrf=csrf, follow_redirects=True)
        data = json.loads(res.data)
        msg = "an email has been sent to you with one time password"
        err_msg = 'Should redirect to otp validation page'
        otp_secret.totp.assert_called()
        mail_queue.enqueue.assert_called()
        assert data.get('flash') == msg, (err_msg, data)
        assert data.get('status') == SUCCESS, (err_msg, data)
        assert data.get('next').split('/')[-1] == 'otpvalidation', (err_msg, data)

        token = data.get('next').split('/')[-2]

        # pass wrong token
        res = self.otpvalidation(follow_redirects=True, otp=OTP,
                                 content_type='application/json')
        data = json.loads(res.data)
        err_msg = 'Should be error'
        assert data['status'] == 'error', (err_msg, data)
        assert data['flash'] == 'Please sign in.', (err_msg, data)

        # pass wrong otp
        res = self.otpvalidation(token=token, follow_redirects=True,
                                 content_type='application/json')
        data = json.loads(res.data)
        err_msg = 'There should be an invalid OTP error message'
        assert data['status'] == 'error', (err_msg, data)
        msg = 'Invalid one time password, a newly generated one time password was sent to your email.'
        assert data['flash'] == msg, (err_msg, data)

        # pass right otp
        res = self.otpvalidation(token=token, follow_redirects=True, otp=OTP,
                                 content_type='application/json')
        data = json.loads(res.data)
        err_msg = 'There should not be an invalid OTP error message'
        assert data['status'] == 'success', (err_msg, data)

        # Log out
        res = self.signout(content_type="application/json",
                           follow_redirects=False)
        msg = "You are now signed out"
        data = json.loads(res.data)
        assert data.get('flash') == msg, (msg, data)
        assert data.get('status') == SUCCESS, data
        assert data.get('next') == '/', data

    @patch('pybossa.view.account.otp.retrieve_user_otp_secret')
    @patch('pybossa.otp.OtpAuth')
    @with_context_settings(ENABLE_TWO_FACTOR_AUTH=True)
    def test_login_expired_otp(self, OtpAuth, retrieve_user_otp_secret):
        """Test expired otp json"""
        self.register()
        # Log out as the registration already logs in the user
        self.signout()

        res = self.signin(method="GET", content_type="application/json",
                          follow_redirects=False)
        data = json.loads(res.data)
        err_msg = "There should be a form with two keys email & password"
        csrf = data['form'].get('csrf')
        assert data.get('title') == "Sign in", data
        assert 'email' in data.get('form').keys(), (err_msg, data)
        assert 'password' in data.get('form').keys(), (err_msg, data)

        OTP = '1234'
        otp_secret = OtpAuth.return_value
        otp_secret.totp.return_value = OTP
        retrieve_user_otp_secret.return_value = None

        res = self.signin(content_type="application/json",
                          csrf=csrf, follow_redirects=True)
        data = json.loads(res.data)

        token = data.get('next').split('/')[-2]

        # pass otp - mock expired
        res = self.otpvalidation(token=token, follow_redirects=True, otp=OTP,
                                 content_type='application/json')
        data = json.loads(res.data)
        err_msg = 'OTP should be expired'
        assert data['status'] == ERROR, (err_msg, data)
        assert 'Expired one time password' in data.get('flash'), (err_msg, data)

    @with_context
    @patch('pybossa.view.projects.rank', autospec=True)
    def test_project_index_sorting(self, mock_rank):
        """Test WEB Project index parameters passed for sorting."""
        self.register()
        self.signin()
        self.create()
        project = db.session.query(Project).get(1)
        project.set_password('hello')

        order_by = u'n_volunteers'
        desc = True
        query = 'orderby=%s&desc=%s' % (order_by, desc)

        # Test named category
        url = 'project/category/%s?%s' % (Fixtures.cat_1, query)
        self.app.get(url, follow_redirects=True)
        assert mock_rank.call_args_list[0][0][0][0]['name'] == project.name
        assert mock_rank.call_args_list[0][0][1] == order_by
        assert mock_rank.call_args_list[0][0][2] == desc

        # Test featured
        project.featured = True
        project_repo.save(project)
        url = 'project/category/featured?%s' % query
        self.app.get(url, follow_redirects=True)
        assert mock_rank.call_args_list[1][0][0][0]['name'] == project.name
        assert mock_rank.call_args_list[1][0][1] == order_by
        assert mock_rank.call_args_list[1][0][2] == desc

        # Test draft
        project.featured = False
        project.published = False
        project_repo.save(project)
        url = 'project/category/draft/?%s' % query
        res = self.app.get(url, follow_redirects=True)
        assert mock_rank.call_args_list[2][0][0][0]['name'] == project.name
        assert mock_rank.call_args_list[2][0][1] == order_by
        assert mock_rank.call_args_list[2][0][2] == desc

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           side_effect=SyncUnauthorized('ProjectSyncer'))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
            return_value={'id': 1})
    def test_project_sync_unauthorized_by_target(self, mock_cat, mock_get, sync_res):
        """Test project sync unauthorized by target server."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(name='test', short_name='test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)
        data = json.loads(res.data)

        expected_flash = ('The API key entered is not authorized to '
                          'perform this action. Please ensure you '
                          'have entered the appropriate API key.')

        assert data['flash'] == expected_flash, data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'error', data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           return_value=FakeResponse(ok=True))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target_owners',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
            return_value={'id': 1})
    def test_project_sync_existing_category_as_admin(self, mock_cat, mock_owners,
                                                     mock_get, mock_sync):
        """Test project sync as admin passes with existing category."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'].startswith('Project sync completed!'), data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'success', data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           return_value=FakeResponse(ok=True))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target_owners',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.sync',
            return_value=FakeResponse(ok=True, content='{"id":1}'))
    def test_project_sync_new_category_as_admin(self, mock_cat_sync, mock_cat,
                                                mock_owners, mock_get, mock_sync):
        """Test project sync as admin passes with new category."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'].startswith('Project sync completed!'), data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'success', data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           return_value=FakeResponse(ok=True))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target_owners',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
            return_value={'id': 1})
    def test_project_sync_existing_category_as_subadmin_owner(self, mock_cat, mock_owners,
                                                              mock_get, mock_sync):
        """Test project sync as subadmin/co-owner passes with existing category."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)

        subadmin = UserFactory.create(subadmin=True)
        subadmin.set_password('1234')
        user_repo.save(subadmin)
        self.signin(email=subadmin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test',
                                        owners_ids=[subadmin.id])
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'].startswith('Project sync completed!'), data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'success', data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           side_effect=SyncUnauthorized('CategorySyncer'))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target_owners',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
           return_value=None)
    def test_project_sync_new_category_as_subadmin_owner(self, mock_cat, mock_owners,
                                                         mock_get, mock_sync):
        """Test project sync as subadmin/co-owner fails with new category."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)

        subadmin = UserFactory.create(subadmin=True)
        subadmin.set_password('1234')
        user_repo.save(subadmin)
        self.signin(email=subadmin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test',
                                        owners_ids=[subadmin.id])
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'].startswith('You are not authorized to create a new category.'), data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'error', data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           return_value=FakeResponse(ok=True))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target_owners',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
            return_value={'id': 1})
    def test_project_sync_as_subadmin_nonowner(self, mock_cat, mock_owners, mock_get, mock_sync):
        """Test project sync as subadmin/non-co-owner fails."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)

        subadmin = UserFactory.create(subadmin=True)
        subadmin.set_password('1234')
        user_repo.save(subadmin)
        self.signin(email=subadmin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)

        assert data['code'] == 403, data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           return_value=FakeResponse(ok=True))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target_owners',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
            return_value={'id': 1})
    def test_project_sync_as_worker(self, mock_cat, mock_owners, mock_get, mock_sync):
        """Test project sync as worker fails."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)

        worker = UserFactory.create()
        worker.set_password('1234')
        user_repo.save(worker)
        self.signin(email=worker.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)

        assert data['code'] == 403, data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           side_effect=NotEnabled)
    def test_project_sync_not_enabled(self, mock_sync):
        """Test project sync not enabled."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'].startswith(
                'The target project is not enabled for syncing.'), data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'error', data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.sync',
           side_effect=Exception)
    def test_project_sync_exception(self, mock_sync):
        """Test project sync exception."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'] == 'An unexpected error occurred while trying to reach your target.', data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'error', data

    @with_context
    @patch('pybossa.syncer.project_syncer.ProjectSyncer._sync',
           return_value=FakeResponse(ok=True))
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target',
            return_value={'id': 1, 'info': {'sync': {'enabled': True}}})
    @patch('pybossa.syncer.project_syncer.ProjectSyncer.get_target_owners',
           return_value=None)
    @patch('pybossa.syncer.project_syncer.CategorySyncer.get_target',
            return_value={'id': 1})
    def test_project_unsync(self, mock_cat, mock_owners, mock_get, mock_sync):
        """Test project unsync."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(name=u'test',
                                        short_name=u'test',
                                        description=u'test')
        project_repo.save(project)

        csrf_url = '/project/{}/update'.format(project.short_name)
        res = self.app_get_json(csrf_url)
        data = json.loads(res.data)
        csrf = data['upload_form']['csrf']

        url = '/project/{}/syncproject'.format(project.short_name)
        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'sync' },
                                 follow_redirects=True)

        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'undo'},
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'].startswith('Last sync has been reverted!'), data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'success', data

        res = self.app_post_json(url=url,
                                 headers={'X-CSRFToken': csrf},
                                 data={'target_key': '1234', 'btn': 'undo'},
                                 follow_redirects=True)
        data = json.loads(res.data)

        assert data['flash'] == 'There is nothing to revert.', data
        assert data['next'] == csrf_url, data
        assert data['status'] == 'warning', data

    @with_context
    def test_fetch_lock(self):
        """Test fetch lock works."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        # Test locked_scheduler
        project = ProjectFactory.create(owner=admin, short_name='test')
        url = '/project/{}/tasks/scheduler'.format(project.short_name)
        new_url = url + '?api_key={}'.format(admin.api_key)
        self.app_post_json(new_url, data=dict(sched='locked_scheduler'))
        task = TaskFactory.create(project=project)
        url = '/project/{}/tasks/timeout'.format(project.short_name)
        new_url = url + '?api_key={}'.format(admin.api_key)
        self.app_post_json(new_url, data=dict(timeout='99'))

        self.app.get('/project/{}/newtask'.format(project.short_name),
                     follow_redirects=True)
        res = self.app_get_json('/api/task/{}/lock'.format(task.id))
        data = json.loads(res.data)

        assert res.status_code == 200
        assert isinstance(data['expires'], float)
        assert data['success'] == True

        # Test user_pref_scheduler
        project2 = ProjectFactory.create(owner=admin, short_name='test2')
        url = '/project/{}/tasks/scheduler'.format(project2.short_name)
        new_url = url + '?api_key={}'.format(admin.api_key)
        self.app_post_json(new_url, data=dict(sched='user_pref_scheduler'))
        task = TaskFactory.create(project=project2)
        url = '/project/{}/tasks/timeout'.format(project2.short_name)
        new_url = url + '?api_key={}'.format(admin.api_key)
        self.app_post_json(new_url, data=dict(timeout='99'))

        self.app.get('/project/{}/newtask'.format(project2.short_name),
                     follow_redirects=True)
        res = self.app_get_json('/api/task/{}/lock'.format(task.id))
        data = json.loads(res.data)

        assert res.status_code == 200
        assert isinstance(data['expires'], float)
        assert data['success'] == True

    @with_context
    def test_fetch_lock_not_found(self):
        """Test fetch lock not found."""
        admin = UserFactory.create(admin=True)
        admin.set_password('1234')
        user_repo.save(admin)
        self.signin(email=admin.email_addr, password='1234')

        project = ProjectFactory.create(owner=admin, short_name='test')
        project2 = ProjectFactory.create(owner=admin, short_name='test2')
        url = '/project/{}/tasks/scheduler'.format(project.short_name)
        new_url = url + '?api_key={}'.format(admin.api_key)
        self.app_post_json(new_url, data=dict(sched='locked_scheduler'))
        task = TaskFactory.create(project=project2)
        url = '/project/{}/tasks/timeout'.format(project.short_name)
        new_url = url + '?api_key={}'.format(admin.api_key)
        self.app_post_json(new_url, data=dict(timeout='99'))

        self.app.get('/project/{}/newtask'.format(project.short_name),
                     follow_redirects=True)
        res = self.app_get_json('/api/task/{}/lock'.format(task.id))
        data = json.loads(res.data)

        assert res.status_code == 404

    @with_context
    def test_fetch_lock_without_task(self):
        """Test fetch lock fails for a non-existent task."""
        self.register()
        self.signin()

        res = self.app_get_json('/api/task/{}/lock'.format(999))

        assert res.status_code == 400

    @with_context
    @patch('pybossa.view.projects.rank', autospec=True)
    def test_project_index_historical_contributions(self, mock_rank):
        self.create()
        user = user_repo.get(2)
        url = 'project/category/historical_contributions?api_key={}'.format(user.api_key)
        with patch.dict(self.flask_app.config, {'HISTORICAL_CONTRIBUTIONS_AS_CATEGORY': True}):
            res = self.app.get(url, follow_redirects=True)
            assert '<h1>Historical Contributions Projects</h1>' in res.data
            assert not mock_rank.called

    @with_context
    def test_export_task_zip_download_anon(self):
        """Test export task with zip download disabled for anon."""
        project = ProjectFactory.create(zip_download=False)
        url = '/project/%s/tasks/export' % project.short_name
        res = self.app.get(url, follow_redirects=True)
        assert 'This feature requires being logged in' in res.data

    @with_context
    def test_export_task_zip_download_not_owner(self):
        """Test export task with zip download disabled for not owner."""
        admin, owner, user = UserFactory.create_batch(3)
        project = ProjectFactory.create(zip_download=False, owner=owner)
        url = '/project/%s/tasks/export?api_key=%s' % (project.short_name,
                                                       user.api_key)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 403

    @with_context
    def test_export_task_zip_download_owner(self):
        """Test export task with zip download disabled for owner."""
        admin, owner, user = UserFactory.create_batch(3)
        project = ProjectFactory.create(zip_download=False, owner=owner)
        task = TaskFactory.create_batch(3, project=project)
        url = '/project/%s/tasks/export?api_key=%s&type=task&format=csv' % (project.short_name,
                                                       owner.api_key)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 200, res.status_code

    @with_context
    def test_export_task_zip_download_admin(self):
        """Test export task with zip download disabled for admin."""
        admin, owner, user = UserFactory.create_batch(3)
        project = ProjectFactory.create(zip_download=False, owner=owner)
        task = TaskFactory.create_batch(3, project=project)
        url = '/project/%s/tasks/export?api_key=%s&type=task&format=csv' % (project.short_name,
                                                       admin.api_key)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 200, res.status_code

    @with_context
    def test_browse_task_zip_download_anon(self):
        """Test browse task with zip download disabled for anon."""
        project = ProjectFactory.create(zip_download=False)
        url = '/project/%s/tasks/browse' % project.short_name
        res = self.app.get(url, follow_redirects=True)
        assert 'This feature requires being logged in' in res.data

    @with_context
    def test_browse_task_zip_download_not_owner(self):
        """Test browse task with zip download disabled for not owner."""
        admin, owner, user = UserFactory.create_batch(3)
        project = ProjectFactory.create(zip_download=False, owner=owner)
        url = '/project/%s/tasks/browse?api_key=%s' % (project.short_name,
                                                       user.api_key)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 403

    @with_context
    def test_browse_task_zip_download_owner(self):
        """Test browse task with zip download disabled for owner."""
        admin, owner, user = UserFactory.create_batch(3)
        project = ProjectFactory.create(zip_download=False, owner=owner)
        task = TaskFactory.create_batch(20, project=project)
        url = '/project/%s/tasks/browse?api_key=%s' % (project.short_name,
                                                       owner.api_key)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 200, res.status_code

    @with_context
    def test_browse_task_zip_download_admin(self):
        """Test browse task with zip download disabled for admin."""
        admin, owner, user = UserFactory.create_batch(3)
        project = ProjectFactory.create(zip_download=False, owner=owner)
        task = TaskFactory.create_batch(20, project=project)
        url = '/project/%s/tasks/browse?api_key=%s' % (project.short_name,
                                                       admin.api_key)
        res = self.app.get(url, follow_redirects=True)
        assert res.status_code == 200, res.status_code

    @with_context
    def test_projects_account(self):
        """Test projecs on profiles are good."""
        owner, contributor = UserFactory.create_batch(2)
        info = dict(passwd_hash='foo', foo='bar')
        project = ProjectFactory.create(owner=owner, info=info)
        TaskRunFactory.create(project=project, user=contributor)

        url = '/account/%s/?api_key=%s' % (contributor.name, owner.api_key)
        res = self.app_get_json(url)
        print(res.data)
        data = json.loads(res.data)
        assert 'projects' in data.keys(), data.keys()
        assert len(data['projects']) == 1, len(data['projects'])
        tmp = data['projects'][0]
        for key in info.keys():
            assert key not in tmp['info'].keys()

        url = '/account/%s/?api_key=%s' % (owner.name, contributor.api_key)
        res = self.app_get_json(url)
        data = json.loads(res.data)
        assert len(data['projects']) == 0, len(data['projects'])
        assert 'projects_created' in data.keys(), data.keys()
        assert len(data['projects_created']) == 1, len(data['projects_created'])
        tmp = data['projects_created'][0]
        for key in info.keys():
            assert key not in tmp['info'].keys()

        url = '/account/%s/?api_key=%s' % (owner.name,
                                           owner.api_key)
        res = self.app_get_json(url)
        data = json.loads(res.data)
        assert 'projects_published' in data.keys(), data.keys()
        assert len(data['projects_published']) == 1, len(data['projects_published'])
        tmp = data['projects_published'][0]
        for key in info.keys():
            assert key in tmp['info'].keys()

    @with_context
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.render_template')
    @patch('pybossa.view.account.signer')
    @patch('pybossa.view.account.app_settings.upref_mdata.get_upref_mdata_choices')
    @patch('pybossa.cache.task_browse_helpers.app_settings.upref_mdata')
    def test_register_with_upref_mdata(self, upref_mdata, get_upref_mdata_choices, signer, render, queue):
        """Test WEB register user with user preferences set"""
        from flask import current_app
        get_upref_mdata_choices.return_value = dict(languages=[("en", "en"), ("sp", "sp")],
                                    locations=[("us", "us"), ("uk", "uk")],
                                    timezones=[("", ""), ("ACT", "Australia Central Time")],
                                    user_types=[("Researcher", "Researcher"), ("Analyst", "Analyst")])

        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = dict(fullname="AJD", name="ajd",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="ajd@example.com",
                    consent=True, user_type="Analyst",
                    languages="sp", locations="uk",
                    timezone="")
        self.register()
        self.signin()
        res = self.app.post('/account/register', data=data)
        assert res.status_code == 302, res.status_code
        assert res.mimetype == 'text/html', res
        user = user_repo.get_by(name='ajd')
        assert user.consent, user
        assert user.name == 'ajd', user
        assert user.email_addr == 'ajd@example.com', user
        expected_upref = dict(languages=['sp'], locations=['uk'])

        assert user.user_pref == expected_upref, "User preferences did not matched"

        upref_data = dict(languages="en", locations="us",
                        user_type="Researcher", timezone="ACT",
                        work_hours_from="10:00", work_hours_to="17:00",
                        review="user with research experience")
        res = self.app.post('/account/save_metadata/ajd',
                data=upref_data, follow_redirects=True)
        assert res.status_code == 200, res.status_code
        user = user_repo.get_by(name='ajd')
        expected_upref = dict(languages=['en'], locations=['us'])
        assert user.user_pref == expected_upref, "User preferences did not matched"

        metadata = user.info['metadata']
        timezone = metadata['timezone']
        work_hours_from = metadata['work_hours_from']
        work_hours_to = metadata['work_hours_to']
        review = metadata['review']
        assert metadata['timezone'] == upref_data['timezone'], "timezone not updated"
        assert metadata['work_hours_from'] == upref_data['work_hours_from'], "work hours from not updated"
        assert metadata['work_hours_to'] == upref_data['work_hours_to'], "work hours to not updated"
        assert metadata['review'] == upref_data['review'], "review not updated"

    @with_context
    @patch('pybossa.view.account.app_settings.upref_mdata.get_upref_mdata_choices')
    @patch('pybossa.cache.task_browse_helpers.app_settings.upref_mdata')
    def test_register_with_invalid_upref_mdata(self, upref_mdata, get_valid_user_preferences):
        """Test WEB register user - invalid user preferences cannot be set"""
        from flask import current_app
        get_valid_user_preferences.return_value = dict(languages=[("en", "en"), ("sp", "sp")],
                                    locations=[("us", "us"), ("uk", "uk")],
                                    timezones=[("", ""), ("ACT", "Australia Central Time")],
                                    user_types=[("Researcher", "Researcher"), ("Analyst", "Analyst")])

        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        data = dict(fullname="AJD", name="ajd",
                    password="p4ssw0rd", confirm="p4ssw0rd",
                    email_addr="ajd@example.com",
                    consent=True, user_type="Analyst",
                    languages="sp", locations="uk",
                    timezone="")
        self.register()
        self.signin()
        res = self.app.post('/account/register', data=data)
        assert res.status_code == 302, res.status_code
        assert res.mimetype == 'text/html', res
        user = user_repo.get_by(name='ajd')
        assert user.consent, user
        assert user.name == 'ajd', user
        assert user.email_addr == 'ajd@example.com', user
        expected_upref = dict(languages=['sp'], locations=['uk'])
        assert user.user_pref == expected_upref, "User preferences did not matched"

        # update invalid user preferences
        upref_invalid_data = dict(languages="ch", locations="jp",
            user_type="Researcher", timezone="ACT",
            work_hours_from="10:00", work_hours_to="17:00",
            review="user with research experience")
        res = self.app.post('/account/save_metadata/johndoe',
                data=upref_invalid_data, follow_redirects=True)
        assert res.status_code == 200, res.status_code
        user = user_repo.get_by(name='ajd')
        invalid_upref = dict(languages=['ch'], locations=['jp'])
        assert user.user_pref != invalid_upref, "Invalid preferences should not be updated"

    @with_context
    def test_task_redundancy_update_tasks_created_within_max_date_range(self):
        """Test task redundancy update applies to tasks created within days as per configured under REDUNDANCY_UPDATE_EXPIRATION"""

        self.register()
        self.signin()
        self.new_project()

        project = db.session.query(Project).first()
        project.published = True
        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
        past_10days = (datetime.utcnow() - timedelta(10)).strftime('%Y-%m-%dT%H:%M:%S')
        past_30days = (datetime.utcnow() - timedelta(30)).strftime('%Y-%m-%dT%H:%M:%S')
        past_60days = (datetime.utcnow() - timedelta(60)).strftime('%Y-%m-%dT%H:%M:%S')
        future_10days = (datetime.utcnow() + timedelta(10)).strftime('%Y-%m-%dT23:00:00')

        task = Task(project_id=project.id, n_answers=1, created=now)
        db.session.add(task)
        db.session.commit()

        # redundancy updated with filter containing valid date range
        filter = dict(n_answers=2, filters=dict())
        res = self.app.post('/project/{}/tasks/redundancyupdate'.format(project.short_name),
            data=json.dumps(filter), content_type='application/json', follow_redirects=True)
        assert task.n_answers == 2, "Updated task redundancy must be 2"

        # future date in filter updates redundancy for 30 days period from current date
        filter = dict(n_answers=3, filters=dict(created_from=past_10days, created_to=future_10days))
        res = self.app.post('/project/{}/tasks/redundancyupdate'.format(project.short_name),
             data=json.dumps(filter), content_type='application/json', follow_redirects=True)
        assert task.n_answers == 3, "Updated task redundancy must be 3"

        # bunch of tasks created in different period. however, redundancy is updated
        # for tasks created were within 30 days range from current date
        tasks_10days = []
        for _ in range(5):
            task = Task(project_id=project.id, n_answers=1, created=past_10days)
            db.session.add(task)
            db.session.commit()
            tasks_10days.append(task)

        tasks_60days = []
        for _ in range(3):
            task = Task(project_id=project.id, n_answers=1, created=past_60days)
            db.session.add(task)
            db.session.commit()
            tasks_60days.append(task)

        filter = dict(n_answers=4, filters=dict(created_from=past_30days, created_to=now))
        res = self.app.post(u'/project/{}/tasks/redundancyupdate'.format(project.short_name),
             data=json.dumps(filter), content_type='application/json', follow_redirects=True)

        # updated redundancy
        for task in tasks_10days:
            assert task.n_answers == 4, "Task created 10 days old should have updated redundancy of 4"

        for task in tasks_60days:
            assert task.n_answers == 1, "Task created 60 days old should have redundancy of 1"

    @with_context
    @patch('pybossa.view.projects.mail_queue', autospec=True)
    def test_update_tasks_redundancy_updates_email_sent_for_redundancy_not_updated(self, email_queue):
        """Test update_tasks_redundancy sends email for tasks not updated"""

        self.register()
        self.signin()
        user = User.query.first()
        project = ProjectFactory.create(owner=user)
        tasks = TaskFactory.create_batch(2, project=project, n_answers=1)
        tasks[0].info = {"file__upload_url": "https://mybucket/test.pdf"}
        taskrun = TaskRunFactory.create(task=tasks[0], user=user)

        # update redundancy passing filters
        filter = dict(n_answers=2, filters=dict())
        res = self.app.post(u'/project/{}/tasks/redundancyupdate'.format(project.short_name),
             data=json.dumps(filter), content_type='application/json', follow_redirects=True)

        # completed tasks redundancy wont be updated
        assert tasks[0].state == 'completed', tasks[0].state
        assert tasks[0].n_answers == 1, tasks[0].n_answers

        # updated task redundancy to be 2 for second task
        assert tasks[1].state == 'ongoing', tasks[1].state
        assert tasks[1].n_answers == 2, tasks[1].n_answers

        assert send_mail == email_queue.enqueue.call_args[0][0], "send_mail not called"
        email_data = email_queue.enqueue.call_args[0][1]
        assert 'subject' in email_data.keys()
        assert 'recipients' in email_data.keys()
        assert 'body' in email_data.keys()

        email_content = email_data['body']
        expected_email_content = ('Redundancy could not be updated for tasks containing files '
            'that are either completed or older than {} days.\nTask Ids\n{}'
            .format(task_repo.rdancy_upd_exp, tasks[0].id))
        assert expected_email_content == email_content, "Email should be sent with list of tasks whose redundancy could not be updated"

    @with_context
    def test_individual_task_redundancy_update(self):
        """Test task redundancy updated for single task"""

        self.register()
        self.signin()
        self.new_project()


        project = db.session.query(Project).first()
        project.published = True
        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')

        task = Task(project_id=project.id, n_answers=1, created=now)
        db.session.add(task)
        db.session.commit()

        # redundancy updated with filter containing single task
        filter = dict(n_answers=2, filters=dict(), taskIds=[task.id])
        res = self.app.post('/project/{}/tasks/redundancyupdate'.format(project.short_name),
            data=json.dumps(filter), content_type='application/json', follow_redirects=True)
        assert task.n_answers == 2, "Updated task redundancy must be 2"

        # redundancy not updated for single task when new redundancy passed is same as old
        filter = dict(n_answers=2, filters=dict(), taskIds=[task.id])
        res = self.app.post('/project/{}/tasks/redundancyupdate'.format(project.short_name),
            data=json.dumps(filter), content_type='application/json', follow_redirects=True)
        assert task.n_answers == 2, "Task redundancy should not have been updated"

    @with_context
    def test_redundancy_update_returns_right_msg(self):
        """Test task redundancy update returns appropriate message"""

        self.register()
        self.signin()
        self.new_project()

        user = User.query.first()
        project = db.session.query(Project).first()
        project.published = True

        task = Task(project_id=project.id, n_answers=1)
        task.info = {"file__upload_url": "https://mybucket/test.pdf"}
        db.session.add(task)
        db.session.commit()

        taskrun = TaskRunFactory.create(task=task, user=user)

        req_data = dict(n_answers=2, taskIds=[task.id])
        res = self.app.post('/project/{}/tasks/redundancyupdate'.format(project.short_name),
        data=json.dumps(req_data), content_type='application/json', follow_redirects=False)

        assert res.status_code == 200, res.status_code
        assert task.n_answers == 1, "redundancy not updated for completed task"
        assert task.state == 'completed', "status not updated for completed task"

    @with_context
    def test_assign_users_to_project(self):
        """Test assign users to project based on data access levels"""

        from pybossa.view.projects import data_access_levels

        self.register()
        self.signin()
        self.new_project()
        project = db.session.query(Project).first()

        project.info['data_access'] = ["L1"]
        user_access = dict(select_users=["L2"])

        with patch.dict(data_access_levels, self.patch_data_access_levels):
            res = self.app.post(u'/project/{}/assign-users'.format(project.short_name),
                 data=json.dumps(user_access), content_type='application/json', follow_redirects=True)
            data = json.loads(res.data)
            assert data.get('status') == 'warning', data
            assert "Cannot assign users. There is no user matching data access level for this project" in data.get('flash'), data


        user = User.query.first()
        user.info['data_access'] = ["L1"]
        user_access = dict(select_users=["L1"])
        with patch.dict(data_access_levels, self.patch_data_access_levels):
            res = self.app.post(u'/project/{}/assign-users'.format(project.short_name),
                 data=json.dumps(user_access), content_type='application/json', follow_redirects=True)
            data = json.loads(res.data)
            assert data.get('status') == 'success', data
            assert "Users unassigned or no user assigned to project" in data.get('flash'), data

    @with_context
    @patch('pybossa.view.account.send_mail', autospec=True)
    @patch('pybossa.view.account.mail_queue', autospec=True)
    @patch('pybossa.view.account.render_template')
    @patch('pybossa.view.account.signer')
    def test_validate_email_once(self, signer, render, queue, send_mail):
        """Test validate email only once."""
        from flask import current_app
        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = False
        user = UserFactory.create()
        signer.dumps.return_value = ''
        render.return_value = ''
        url = '/account/{}/update?api_key={}'.format(user.name, user.api_key)
        data = {'id': user.id, 'fullname': user.fullname,
                'name': user.name,
                'locale': user.locale,
                'email_addr': 'new@fake.com',
                'btn': 'Profile'}
        res = self.app.post(url, data=data, follow_redirects=True)

        current_app.config['ACCOUNT_CONFIRMATION_DISABLED'] = True
        assert b'Use a valid email account' in str(res.data), res.data


class TestWebUserMetadataUpdate(web.Helper):

    original = {
        'user_type': 'Curator',
        'languages': ["Afrikaans", "Albanian", "Welsh"],
        'work_hours_from': '08:00',
        'work_hours_to': '15:00',
        'review': 'Original Review',
        'timezone': "AET",
        'locations': ['Bonaire', 'Wallis and Futuna']
    }

    update = {
        'user_type': 'Researcher',
        'languages': ["Afrikaans", "Albanian"],
        'work_hours_from': '09:00',
        'work_hours_to': '16:00',
        'review': 'Updated Review',
        'timezone': "AGT",
        'locations': ['Vanuatu']
    }

    def create_user(self, **kwargs):
        data = self.original
        user = UserFactory.create(
            info={
                'metadata':{
                    'user_type':data['user_type'],
                    'work_hours_from':data['work_hours_from'],
                    'work_hours_to':data['work_hours_to'],
                    'timezone':data['timezone'],
                    'review':data['review']
                }
            },
            user_pref={
                'languages':data['languages'],
                'locations':data['locations']
            },
            **kwargs
        )
        data_created = get_user_data_as_form(user)
        for k,v in six.iteritems(data):
            assert v == data_created[k], 'Created user field [{}] does not equal specified data'.format(k)
        return user

    def assert_updates_applied_correctly(self, user_id, disabled=update.keys()):
        user_updated = user_repo.get(user_id)
        updated = get_user_data_as_form(user_updated)

        enabled = set(self.update.keys()) - set(disabled)

        for k in enabled:
            assert updated[k] == self.update[k], 'Enabled field [{}] did not get updated.'.format(k)
        for k in disabled:
            original_value = self.original[k]
            updated_value = updated[k]
            assert updated_value == original_value, 'Disabled field [{}] got updated from [{}] to [{}].'.format(k, original_value, updated_value)

    def update_metadata(self, user_name):
        url = u'/account/save_metadata/{}'.format(user_name)
        res = self.app.post(
            url,
            data=self.update,
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    def assert_is_normal(self, user):
        assert not user.admin and not user.subadmin

    def assert_is_subadmin(self, user):
        assert not user.admin and user.subadmin

    def mock_upref_mdata_choices(self, get_upref_mdata_choices):
        def double(x): return (x,x)
        get_upref_mdata_choices.return_value = dict(
            languages=map(double,["Afrikaans", "Albanian", "Welsh"]),
            locations=map(double, ['Bonaire', 'Wallis and Futuna', 'Vanuatu']),
            timezones=[("AET", "Australia Eastern Time"), ("AGT", "Argentina Standard Time")],
            user_types=map(double, ["Researcher", "Analyst", "Curator"])
        )

    def test_update_differs_from_orginal(self):
        '''Test updates are different from original values'''
        for k,v in six.iteritems(self.update):
            assert v != self.original[k], '[{}] is same in original and update'.format(k)

    @with_context
    @patch('pybossa.view.account.app_settings.upref_mdata.get_upref_mdata_choices')
    @patch('pybossa.cache.task_browse_helpers.app_settings.upref_mdata')
    def test_normal_user_cannot_update_own_user_type(self, upref_mdata, get_upref_mdata_choices):
        """Test normal user can update their own metadata except for user_type"""
        self.mock_upref_mdata_choices(get_upref_mdata_choices)
        # First user created is automatically admin, so get that out of the way.
        user_admin = UserFactory.create()
        user_normal = self.create_user()
        self.assert_is_normal(user_normal)
        self.signin_user(user_normal)
        self.update_metadata(user_normal.name)
        disabled = ['user_type']
        self.assert_updates_applied_correctly(user_normal.id, disabled)

    @with_context
    @patch('pybossa.view.account.app_settings.upref_mdata.get_upref_mdata_choices')
    @patch('pybossa.cache.task_browse_helpers.app_settings.upref_mdata')
    def test_admin_user_can_update_own_metadata(self, upref_mdata, get_upref_mdata_choices):
        '''Test admin can update their own metadata'''
        self.mock_upref_mdata_choices(get_upref_mdata_choices)
        user_admin = self.create_user()
        assert user_admin.admin
        self.signin_user(user_admin)
        self.update_metadata(user_admin.name)
        disabled = []
        self.assert_updates_applied_correctly(user_admin.id, disabled)

    @with_context
    @patch('pybossa.view.account.app_settings.upref_mdata.get_upref_mdata_choices')
    @patch('pybossa.cache.task_browse_helpers.app_settings.upref_mdata')
    def test_subadmin_user_can_update_own_metadata(self, upref_mdata, get_upref_mdata_choices):
        '''Test subadmin can update their own metadata'''
        self.mock_upref_mdata_choices(get_upref_mdata_choices)
        # First user created is automatically admin, so get that out of the way.
        user_admin = UserFactory.create()
        user_subadmin = self.create_user(subadmin=True)
        self.assert_is_subadmin(user_subadmin)
        self.signin_user(user_subadmin)
        self.update_metadata(user_subadmin.name)
        disabled = []
        self.assert_updates_applied_correctly(user_subadmin.id, disabled)

    @with_context
    @patch('pybossa.view.account.app_settings.upref_mdata.get_upref_mdata_choices')
    @patch('pybossa.cache.task_browse_helpers.app_settings.upref_mdata')
    def test_subadmin_user_can_update_normal_user_metadata(self, upref_mdata, get_upref_mdata_choices):
        '''Test subadmin can update normal user metadata'''
        self.mock_upref_mdata_choices(get_upref_mdata_choices)
        # First user created is automatically admin, so get that out of the way.
        user_admin = UserFactory.create()
        user_subadmin = UserFactory.create(subadmin=True)
        self.assert_is_subadmin(user_subadmin)
        user_normal = self.create_user()
        self.assert_is_normal(user_normal)
        self.signin_user(user_subadmin)
        self.update_metadata(user_normal.name)
        disabled = []
        self.assert_updates_applied_correctly(user_normal.id, disabled)

    @with_context
    def test_subadmin_user_cannot_update_other_subadmin_metadata(self):
        '''Test subadmin cannot update other subadmin metadata'''
        # First user created is automatically admin, so get that out of the way.
        user_admin = UserFactory.create()
        user_subadmin = UserFactory.create(subadmin=True)
        self.assert_is_subadmin(user_subadmin)
        user_subadmin_updated =self.create_user(subadmin=True)
        self.assert_is_subadmin(user_subadmin_updated)
        self.signin_user(user_subadmin)
        self.update_metadata(user_subadmin_updated.name)
        self.assert_updates_applied_correctly(user_subadmin_updated.id)

    @with_context
    def test_subadmin_user_cannot_update_other_admin_metadata(self):
        '''Test subadmin cannot update admin metadata'''
        # First user created is automatically admin, so get that out of the way.
        user_admin_updated = self.create_user()
        assert user_admin_updated.admin
        user_subadmin = UserFactory.create(subadmin=True)
        self.assert_is_subadmin(user_subadmin)
        self.signin_user(user_subadmin)
        self.update_metadata(user_admin_updated.name)
        self.assert_updates_applied_correctly(user_admin_updated.id)

    @with_context
    def test_normal_user_cannot_update_other_user_metadata(self):
        '''Test normal user cannot update other user metadata'''
        # First user created is automatically admin, so get that out of the way.
        user_admin = UserFactory.create()
        user_normal = UserFactory.create()
        self.assert_is_normal(user_normal)
        user_normal_updated = self.create_user()
        self.assert_is_normal(user_normal_updated)
        self.signin_user(user_normal)
        self.update_metadata(user_normal_updated.name)
        self.assert_updates_applied_correctly(user_normal_updated.id)


class TestWebQuizModeUpdate(web.Helper):

    disabled_update = {
        'questions_per_quiz': 20,
        'correct_answers_to_pass': 15,
        'garbage': 'junk'
    }

    enabled_update = dict.copy(disabled_update)
    enabled_update['enabled'] ='y'

    disabled_result = {
        'enabled': False,
        'questions': disabled_update['questions_per_quiz'],
        'pass': disabled_update['correct_answers_to_pass']
    }

    enabled_result = dict.copy(disabled_result)
    enabled_result['enabled'] = True

    invalid_update = dict.copy(enabled_update)
    invalid_update['correct_answers_to_pass'] = 30

    def update(self, update, result):
        admin = UserFactory.create()
        self.signin_user(admin)
        project = ProjectFactory.create(owner=admin)
        res = self.update_project(project, update)
        updated_project = project_repo.get(project.id)
        quiz = updated_project.info.get('quiz')
        assert quiz == result

    def update_project(self, project, update, follow_redirects=True):
        return self.app.post(
            self.get_url(project),
            data=update,
            content_type="multipart/form-data",
            follow_redirects=follow_redirects,
        )

    def get_url(self, project):
        return u'/project/{}/quiz-mode'.format(project.short_name)

    @with_context
    def test_enable(self):
        '''Test project quiz mode form enables quiz mode'''
        self.update(self.enabled_update, self.enabled_result)

    @with_context
    def test_disable(self):
        '''Test project quiz mode form disables quiz mode'''
        self.update(self.disabled_update, self.disabled_result)

    @with_context
    def test_requires_login(self):
        '''Test login is required to update project quiz mode settings'''
        admin = UserFactory.create()
        project = ProjectFactory.create(owner=admin)

        result = self.update_project(project, self.enabled_update, follow_redirects=False)
        assert result.status_code == 302

    @with_context
    def test_display_new_project(self):
        '''Test displaying quiz mode settings for new project'''
        admin = UserFactory.create()
        self.signin_user(admin)
        project = ProjectFactory.create(owner=admin)

        result = self.app.get(
            self.get_url(project),
            follow_redirects=True,
        )
        assert result.status_code == 200

    @with_context
    def test_invalid(self):
        '''Test invalid update has no effect'''
        self.update(self.invalid_update, None)

    @with_context
    def test_normal_user_cannot_update(self):
        '''Test normal user cannot update project quiz mode'''
        admin = UserFactory.create()
        worker = UserFactory.create()
        assert not worker.admin and not worker.subadmin
        project = ProjectFactory.create(owner=admin)
        self.signin_user(worker)
        result = self.update_project(project, self.enabled_update)
        assert result.status_code == 403
