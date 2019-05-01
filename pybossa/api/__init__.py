# -*- coding: utf8 -*-
# This file is part of PYBOSSA.
#
# Copyright (C) 2015 Scifabric LTD.
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
"""
PYBOSSA api module for exposing domain objects via an API.

This package adds GET, POST, PUT and DELETE methods for:
    * projects,
    * categories,
    * tasks,
    * task_runs,
    * users,
    * global_stats,

"""

from functools import partial
import json
import jwt
from flask import Blueprint, request, abort, Response, make_response
from flask import current_app
from flask_login import current_user
from time import time
from werkzeug.exceptions import NotFound
from pybossa.util import jsonpify, get_user_id_or_ip, fuzzyboolean
from pybossa.util import get_disqus_sso_payload, grant_access_with_api_key
import pybossa.model as model
from pybossa.core import csrf, ratelimits, sentinel, anonymizer
from pybossa.ratelimit import ratelimit
from pybossa.cache.projects import n_tasks
import pybossa.sched as sched
from pybossa.util import sign_task
from pybossa.error import ErrorStatus
from global_stats import GlobalStatsAPI
from task import TaskAPI
from task_run import TaskRunAPI, preprocess_task_run
from project import ProjectAPI
from announcement import AnnouncementAPI
from blogpost import BlogpostAPI
from category import CategoryAPI
from favorites import FavoritesAPI
from pybossa.api.performance_stats import PerformanceStatsAPI
from user import UserAPI
from token import TokenAPI
from result import ResultAPI
from project_stats import ProjectStatsAPI
from helpingmaterial import HelpingMaterialAPI
from pybossa.core import project_repo, task_repo, user_repo
from pybossa.contributions_guard import ContributionsGuard
from pybossa.auth import jwt_authorize_project
from werkzeug.exceptions import MethodNotAllowed, Forbidden
from completed_task import CompletedTaskAPI
from completed_task_run import CompletedTaskRunAPI
from pybossa.cache.helpers import n_available_tasks, n_available_tasks_for_user
from pybossa.sched import (get_project_scheduler_and_timeout, get_scheduler_and_timeout,
                           has_lock, release_lock, Schedulers, get_locks)
from pybossa.api.project_by_name import ProjectByNameAPI
from pybossa.api.pwd_manager import get_pwd_manager
from pybossa.data_access import data_access_levels
from pybossa.task_creator_helper import set_gold_answer

blueprint = Blueprint('api', __name__)

error = ErrorStatus()


@blueprint.route('/')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def index():  # pragma: no cover
    """Return dummy text for welcome page."""
    return 'The %s API' % current_app.config.get('BRAND')


@blueprint.before_request
def _api_authentication_with_api_key():
    """ Allow API access with valid api_key."""
    secure_app_access = current_app.config.get('SECURE_APP_ACCESS', False)
    if secure_app_access:
        grant_access_with_api_key(secure_app_access)


def register_api(view, endpoint, url, pk='id', pk_type='int'):
    """Register API endpoints.

    Registers new end points for the API using classes.

    """
    view_func = view.as_view(endpoint)
    csrf.exempt(view_func)
    blueprint.add_url_rule(url,
                           view_func=view_func,
                           defaults={pk: None},
                           methods=['GET', 'OPTIONS'])
    blueprint.add_url_rule(url,
                           view_func=view_func,
                           methods=['POST', 'OPTIONS'])
    blueprint.add_url_rule('%s/<%s:%s>' % (url, pk_type, pk),
                           view_func=view_func,
                           methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])

register_api(ProjectAPI, 'api_project', '/project', pk='oid', pk_type='int')
register_api(ProjectStatsAPI, 'api_projectstats', '/projectstats', pk='oid', pk_type='int')
register_api(CategoryAPI, 'api_category', '/category', pk='oid', pk_type='int')
register_api(TaskAPI, 'api_task', '/task', pk='oid', pk_type='int')
register_api(TaskRunAPI, 'api_taskrun', '/taskrun', pk='oid', pk_type='int')
register_api(ResultAPI, 'api_result', '/result', pk='oid', pk_type='int')
register_api(UserAPI, 'api_user', '/user', pk='oid', pk_type='int')
register_api(AnnouncementAPI, 'api_announcement', '/announcement', pk='oid', pk_type='int')
register_api(BlogpostAPI, 'api_blogpost', '/blogpost', pk='oid', pk_type='int')
register_api(HelpingMaterialAPI, 'api_helpingmaterial',
             '/helpingmaterial', pk='oid', pk_type='int')
register_api(GlobalStatsAPI, 'api_globalstats', '/globalstats',
             pk='oid', pk_type='int')
register_api(FavoritesAPI, 'api_favorites', '/favorites',
             pk='oid', pk_type='int')
register_api(TokenAPI, 'api_token', '/token', pk='token', pk_type='string')
register_api(CompletedTaskAPI, 'api_completedtask', '/completedtask', pk='oid', pk_type='int')
register_api(CompletedTaskRunAPI, 'api_completedtaskrun', '/completedtaskrun', pk='oid', pk_type='int')
register_api(ProjectByNameAPI, 'api_projectbyname', '/projectbyname', pk='key', pk_type='string')
register_api(PerformanceStatsAPI, 'api_performancestats', '/performancestats', pk='oid', pk_type='int')


def add_task_signature(tasks):
    if current_app.config.get('ENABLE_ENCRYPTION'):
        for task in tasks:
            sign_task(task)

@jsonpify
@blueprint.route('/project/<project_id>/newtask')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def new_task(project_id):
    """Return a new task for a project."""
    # Check if the request has an arg:
    try:
        tasks, timeout, cookie_handler = _retrieve_new_task(project_id)

        if type(tasks) is Response:
            return tasks

        user_id_or_ip = get_user_id_or_ip()
        # If there is a task for the user, return it
        if tasks is not None:
            guard = ContributionsGuard(sentinel.master, timeout=timeout)
            for task in tasks:
                guard.stamp(task, user_id_or_ip)
                if not guard.check_task_presented_timestamp(task, user_id_or_ip):
                    guard.stamp_presented_time(task, user_id_or_ip)
                else:
                    # user returning back for the same task
                    # original presented time has not expired yet
                    # to continue original presented time, extend expiry
                    guard.extend_task_presented_timestamp_expiry(task, user_id_or_ip)

            data = [task.dictize() for task in tasks]
            add_task_signature(data)
            if len(data) == 0:
                response = make_response(json.dumps({}))
            elif len(data) == 1:
                response = make_response(json.dumps(data[0]))
            else:
                response = make_response(json.dumps(data))
            response.mimetype = "application/json"
            cookie_handler(response)
            return response
        return Response(json.dumps({}), mimetype="application/json")
    except Exception as e:
        return error.format_exception(e, target='project', action='GET')


def _retrieve_new_task(project_id):

    project = project_repo.get(project_id)
    if project is None or not(project.published or current_user.admin
        or current_user.id in project.owners_ids):
        raise NotFound

    if current_user.is_anonymous:
        info = dict(
            error="This project does not allow anonymous contributors")
        error = [model.task.Task(info=info)]
        return error, None, lambda x: x

    if current_user.get_quiz_failed(project):
        # User is blocked from project so don't return a task
        return None, None, None

    # check cookie
    pwd_manager = get_pwd_manager(project)
    user_id_or_ip = get_user_id_or_ip()
    if pwd_manager.password_needed(project, user_id_or_ip):
        raise Forbidden("No project password provided")

    if request.args.get('external_uid'):
        resp = jwt_authorize_project(project,
                                     request.headers.get('Authorization'))
        if resp != True:
            return resp, lambda x: x

    if request.args.get('limit'):
        limit = int(request.args.get('limit'))
    else:
        limit = 1

    if limit > 100:
        limit = 100

    if request.args.get('offset'):
        offset = int(request.args.get('offset'))
    else:
        offset = 0

    if request.args.get('orderby'):
        orderby = request.args.get('orderby')
    else:
        orderby = 'id'

    if request.args.get('desc'):
        desc = fuzzyboolean(request.args.get('desc'))
    else:
        desc = False

    user_id = None if current_user.is_anonymous else current_user.id
    user_ip = (anonymizer.ip(request.remote_addr or '127.0.0.1')
               if current_user.is_anonymous else None)
    external_uid = request.args.get('external_uid')
    sched_rand_within_priority = project.info.get('sched_rand_within_priority', False)

    user = user_repo.get(user_id)
    if (
        user.get_quiz_not_started(project)
        and user.get_quiz_enabled(project)
        and not task_repo.get_user_has_task_run_for_project(project_id, user_id)
    ):
        user.set_quiz_status(project, 'in_progress')

    user_repo.update(user)

    task = sched.new_task(project.id,
                          project.info.get('sched'),
                          user_id,
                          user_ip,
                          external_uid,
                          offset,
                          limit,
                          orderby=orderby,
                          desc=desc,
                          rand_within_priority=sched_rand_within_priority,
                          gold_only = user.get_quiz_in_progress(project))

    handler = partial(pwd_manager.update_response, project=project,
                      user=user_id_or_ip)
    return task, project.info.get('timeout'), handler


@jsonpify
@blueprint.route('/app/<short_name>/userprogress')
@blueprint.route('/project/<short_name>/userprogress')
@blueprint.route('/app/<int:project_id>/userprogress')
@blueprint.route('/project/<int:project_id>/userprogress')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def user_progress(project_id=None, short_name=None):
    """API endpoint for user progress.

    Return a JSON object with four fields regarding the tasks for the user:
        { 'done': 10,
          'total: 100,
          'remaining': 90,
          'remaining_for_user': 45
        }
       This will mean that the user has done 10% of the available tasks for the
       project, 90 tasks are yet to be submitted and the user can access 45 of
       them based on user preferences.

    """
    if current_user.is_anonymous:
        return abort(401)
    if project_id or short_name:
        if short_name:
            project = project_repo.get_by_shortname(short_name)
        elif project_id:
            project = project_repo.get(project_id)

        if project:
            # For now, keep this version, but wait until redis cache is
            # used here for task_runs too
            query_attrs = dict(project_id=project.id)
            query_attrs['user_id'] = current_user.id
            taskrun_count = task_repo.count_task_runs_with(**query_attrs)
            num_available_tasks = n_available_tasks(project.id, current_user.id)
            num_available_tasks_for_user = n_available_tasks_for_user(project, current_user.id)
            response = dict(
                done=taskrun_count,
                total=n_tasks(project.id),
                remaining=num_available_tasks,
                remaining_for_user=num_available_tasks_for_user,
                quiz = current_user.get_quiz_for_project(project)
            )
            return Response(json.dumps(response), mimetype="application/json")
        else:
            return abort(404)
    else:  # pragma: no cover
        return abort(404)


@jsonpify
@blueprint.route('/auth/project/<short_name>/token')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def auth_jwt_project(short_name):
    """Create a JWT for a project via its secret KEY."""
    project_secret_key = None
    if 'Authorization' in request.headers:
        project_secret_key = request.headers.get('Authorization')
    if project_secret_key:
        project = project_repo.get_by_shortname(short_name)
        if project and project.secret_key == project_secret_key:
            token = jwt.encode({'short_name': short_name,
                                'project_id': project.id},
                               project.secret_key, algorithm='HS256')
            return token
        else:
            return abort(404)
    else:
        return abort(403)


@jsonpify
@blueprint.route('/disqus/sso')
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def get_disqus_sso_api():
    """Return remote_auth_s3 and api_key for disqus SSO."""
    try:
        if current_user.is_authenticated:
            message, timestamp, sig, pub_key = get_disqus_sso_payload(current_user)
        else:
            message, timestamp, sig, pub_key = get_disqus_sso_payload(None)

        if message and timestamp and sig and pub_key:
            remote_auth_s3 = "%s %s %s" % (message, sig, timestamp)
            tmp = dict(remote_auth_s3=remote_auth_s3, api_key=pub_key)
            return Response(json.dumps(tmp), mimetype='application/json')
        else:
            raise MethodNotAllowed
    except MethodNotAllowed as e:
        e.message = "Disqus keys are missing"
        return error.format_exception(e, target='DISQUS_SSO', action='GET')


@jsonpify
@csrf.exempt
@blueprint.route('/task/<int:task_id>/canceltask', methods=['POST'])
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def cancel_task(task_id=None):
    """Unlock task upon cancel so that same task can be presented again."""
    if not current_user.is_authenticated:
        return abort(401)

    data = request.json
    projectname = data.get('projectname', None)
    project = project_repo.get_by_shortname(projectname)
    if not project:
        return abort(400)

    user_id = current_user.id
    scheduler, timeout = get_scheduler_and_timeout(project)
    if scheduler in (Schedulers.locked, Schedulers.user_pref):
        task_locked_by_user = has_lock(task_id, user_id, timeout)
        if task_locked_by_user:
            release_lock(task_id, user_id, timeout)
            current_app.logger.info(
                'Project {} - user {} cancelled task {}'
                .format(project.id, current_user.id, task_id))

    return Response(json.dumps({'success': True}), 200, mimetype="application/json")


@jsonpify
@blueprint.route('/task/<int:task_id>/lock', methods=['GET'])
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def fetch_lock(task_id):
    """Fetch the time (in seconds) until the current user's
    lock on a task expires.
    """
    if not current_user.is_authenticated:
        return abort(401)

    task = task_repo.get_task(task_id)

    if not task:
        return abort(400)

    scheduler, timeout = get_project_scheduler_and_timeout(
            task.project_id)

    ttl = None
    if scheduler in (Schedulers.locked, Schedulers.user_pref):
        task_locked_by_user = has_lock(
                task.id, current_user.id, timeout)
        if task_locked_by_user:
            locks = get_locks(task.id, timeout)
            ttl = locks.get(str(current_user.id))

    if not ttl:
        return abort(404)

    seconds_to_expire = float(ttl) - time()
    res = json.dumps({'success': True,
                      'expires': seconds_to_expire})

    return Response(res, 200, mimetype='application/json')


@jsonpify
@csrf.exempt
@blueprint.route('/project/<int:project_id>/taskgold', methods=['POST'])
@ratelimit(limit=ratelimits.get('LIMIT'), per=ratelimits.get('PER'))
def task_gold(project_id=None):
    """Make task gold"""
    if not current_user.is_authenticated:
        return abort(401)

    project = project_repo.get(project_id)
    if project is None or not(current_user.admin
        or current_user.id in project.owners_ids):
        raise Forbidden

    task_data = request.json
    task_id = task_data['task_id']
    task = task_repo.get_task(task_id)
    if task.project_id != project_id:
        raise Forbidden

    preprocess_task_run(project_id, task_id, task_data)

    info = task_data['info']
    set_gold_answer(task, project_id, info, task_id)

    task_repo.update(task)

    return Response(json.dumps({'success': True}), 200, mimetype="application/json")
