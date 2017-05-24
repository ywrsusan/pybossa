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

from sqlalchemy.exc import IntegrityError
from sqlalchemy import cast, Date

from pybossa.repositories import Repository
from pybossa.model.task import Task
from pybossa.model.task_run import TaskRun
from pybossa.model import make_timestamp
from pybossa.model.user import User
from pybossa.exc import WrongObjectError, DBIntegrityError
from pybossa.cache import projects as cached_projects
from pybossa.core import uploader
from sqlalchemy import text
from pybossa.cache.task_browse_helpers import get_task_filters
import json


class TaskRepository(Repository):

    # Methods for queries on Task objects
    def get_task(self, id):
        return self.db.session.query(Task).get(id)

    def get_task_by(self, **attributes):
        filters, _, _, _ = self.generate_query_from_keywords(Task, **attributes)
        return self.db.session.query(Task).filter(*filters).first()

    def filter_tasks_by(self, limit=None, offset=0, yielded=False,
                        last_id=None, fulltextsearch=None, desc=False,
                        **filters):

        return self._filter_by(Task, limit, offset, yielded, last_id,
                              fulltextsearch, desc, **filters)

    def filter_tasks_by_g(self, limit=None, offset=0, yielded=False,
                        last_id=None, fulltextsearch=None, desc=False,
                        **filters):
        query = self.create_context(filters, fulltextsearch, Task)
        return self._filter_query(query, Task, limit, offset, last_id, yielded, desc)

    def filter_completed_task_runs_by(self, limit=None, offset=0, yielded=False, **filters):
        # exported col is present in Task table
        # anything passed under filters will be
        # searched in TaskRun table instead of Task
        # exclude exported flag from filters and make
        # it explicitly searchable against Task table
        exp = filters.pop('exported', None)
        if exp is not None:
            query = self.db.session.query(TaskRun).join(Task).\
                filter(TaskRun.task_id == Task.id).\
                filter(Task.state == u'completed').\
                filter(Task.exported == exp).\
                filter_by(**filters)
        else:
            query = self.db.session.query(TaskRun).join(Task).\
                filter(TaskRun.task_id == Task.id).\
                filter(Task.state == u'completed').\
                filter_by(**filters)

        query = query.order_by(TaskRun.id).limit(limit).offset(offset)
        if yielded:
            return query.yield_per(1)
        return query.all()

    def count_tasks_with(self, **filters):
        query_args, _, _, _  = self.generate_query_from_keywords(Task, **filters)
        return self.db.session.query(Task).filter(*query_args).count()

    def filter_tasks_by_user_favorites(self, uid):
        """Return tasks marked as favorited by user.id."""
        tasks = self.db.session.query(Task).filter(Task.fav_user_ids.any(uid)).all()
        return tasks

    def get_task_favorited(self, uid, task_id):
        """Return task marked as favorited by user.id."""
        tasks = self.db.session.query(Task)\
                    .filter(Task.fav_user_ids.any(uid),
                            Task.id==task_id)\
                    .all()
        return tasks

    # Methods for queries on TaskRun objects
    def get_task_run(self, id):
        return self.db.session.query(TaskRun).get(id)

    def get_task_run_by(self, fulltextsearch=None, **attributes):
        filters, _, _, _  = self.generate_query_from_keywords(TaskRun,
                                                    fulltextsearch,
                                                    **attributes)
        return self.db.session.query(TaskRun).filter(*filters).first()

    def filter_task_runs_by(self, limit=None, offset=0, last_id=None,
                            yielded=False, fulltextsearch=None,
                            desc=False, **filters):
        return self._filter_by(TaskRun, limit, offset, yielded, last_id,
                              fulltextsearch, desc, **filters)

    def count_task_runs_with(self, **filters):
        query_args, _, _, _ = self.generate_query_from_keywords(TaskRun, **filters)
        return self.db.session.query(TaskRun).filter(*query_args).count()

    def filter_task_runs_by_g(self, limit=None, offset=0, last_id=None,
                            yielded=False, fulltextsearch=None,
                            desc=False, **filters):
        query = self.create_context(filters, fulltextsearch, TaskRun)
        return self._filter_query(query, TaskRun, limit, offset, last_id, yielded, desc)

    def count_task_runs_with(self, **filters):
        query_args = self.generate_query_from_keywords(TaskRun, **filters)
        return self.db.session.query(TaskRun).filter(*query_args).count()


    # Filter helpers
    def _filter_query(self, query, obj, limit, offset, last_id, yielded, desc):
        if last_id:
            query = query.filter(obj.id > last_id)
            query = query.order_by(obj.id).limit(limit)
        else:
            if desc:
                query = query.order_by(cast(obj.created, Date).desc())\
                        .limit(limit).offset(offset)
            else:
                query = query.order_by(obj.id).limit(limit).offset(offset)
        if yielded:
            limit = limit or 1
            return query.yield_per(limit)
        return query.all()


    # Methods for saving, deleting and updating both Task and TaskRun objects
    def save(self, element):
        self._validate_can_be('saved', element)
        try:
            self.db.session.add(element)
            self.db.session.commit()
            cached_projects.clean_project(element.project_id)
        except IntegrityError as e:
            self.db.session.rollback()
            raise DBIntegrityError(e)

    def update(self, element):
        self._validate_can_be('updated', element)
        try:
            self.db.session.merge(element)
            self.db.session.commit()
            cached_projects.clean_project(element.project_id)
        except IntegrityError as e:
            self.db.session.rollback()
            raise DBIntegrityError(e)

    def delete(self, element):
        self._delete(element)
        project = element.project
        self.db.session.commit()
        cached_projects.clean_project(element.project_id)
        self._delete_zip_files_from_store(project)

    def delete_valid_from_project(self, project, force_reset=False):
        if not force_reset:
            """Delete only tasks that have no results associated."""
            sql = text('''
                DELETE FROM task WHERE task.project_id=:project_id
                AND task.id NOT IN
                (SELECT task_id FROM result
                WHERE result.project_id=:project_id GROUP BY result.task_id);
                ''')
        else:
            """force reset, remove all results."""
            sql = text('''
                BEGIN;

                DELETE FROM result WHERE project_id=:project_id;
                DELETE FROM task_run WHERE project_id=:project_id;                
                DELETE FROM task WHERE task.project_id=:project_id;

                COMMIT;
                ''')
        self.db.session.execute(sql, dict(project_id=project.id))
        self.db.session.commit()
        cached_projects.clean_project(project.id)
        self._delete_zip_files_from_store(project)

    def delete_taskruns_from_project(self, project):
        sql = text('''
                   DELETE FROM task_run WHERE project_id=:project_id;
                   ''')
        self.db.session.execute(sql, dict(project_id=project.id))
        self.db.session.commit()
        cached_projects.clean_project(project.id)
        self._delete_zip_files_from_store(project)

    def update_tasks_redundancy(self, project, n_answers, args=None):
        """update the n_answer of every task from a project and their state.
        Use raw SQL for performance"""
        args = args or {}
        filters, params = get_task_filters(args)
        if n_answers < 1 or n_answers > 1000:
            raise ValueError("Invalid value")

        sql = text('''
                   WITH to_update AS (
                        SELECT task.id as id,
                        coalesce(ct, 0) as n_task_runs, task.n_answers, ft,
                        priority_0, task.created
                        FROM task LEFT OUTER JOIN
                        (SELECT task_id, CAST(COUNT(id) AS FLOAT) AS ct,
                        MAX(finish_time) as ft FROM task_run
                        WHERE project_id=:project_id GROUP BY task_id) AS log_counts
                        ON task.id=log_counts.task_id
                        WHERE task.project_id=:project_id {}
                   )
                   UPDATE task SET n_answers=:n_answers,
                   state='ongoing' WHERE project_id=:project_id
                   AND task.id in (SELECT id from to_update);'''
                   .format(filters))
        self.db.session.execute(sql, dict(n_answers=n_answers,
                                          project_id=project.id,
                                          **params))
        self.db.session.commit()
        self.update_task_state(project.id, n_answers)

    def update_task_state(self, project_id, n_answers):
        # Create temp tables for completed tasks
        sql = text('''
                   CREATE TEMP TABLE complete_tasks ON COMMIT DROP AS (
                   SELECT task.id, array_agg(task_run.id) as task_runs
                   FROM task, task_run
                   WHERE task_run.task_id=task.id
                   AND task.project_id=:project_id
                   GROUP BY task.id
                   having COUNT(task_run.id) >=:n_answers);
                   ''')
        self.db.session.execute(sql, dict(n_answers=n_answers,
                                          project_id=project_id))
        # Set state to completed
        sql = text('''
                   UPDATE task SET state='completed'
                   FROM complete_tasks
                   WHERE complete_tasks.id=task.id;
                   ''')
        self.db.session.execute(sql)
        # Deactivate previous tasks' results (if available)
        # (redundancy was decreased)
        sql = text('''UPDATE result set last_version=false
                   WHERE task_id IN (SELECT id FROM complete_tasks);''')
        self.db.session.execute(sql)
        # Insert result rows (last_version=true)
        sql = text('''
                   INSERT INTO result
                   (created, project_id, task_id, task_run_ids, last_version) (
                    SELECT :ts, :project_id, complete_tasks.id,
                            complete_tasks.task_runs, true
                    FROM complete_tasks);''')
        self.db.session.execute(sql, dict(project_id=project_id,
                                          ts=make_timestamp()))
        # Create temp table for incomplete tasks
        sql = text('''
                   CREATE TEMP TABLE incomplete_tasks ON COMMIT DROP AS (
                   SELECT task.id
                   FROM task
                   WHERE task.project_id=:project_id
                   AND task.id not IN (SELECT id FROM complete_tasks));
                   ''')
        self.db.session.execute(sql, dict(project_id=project_id))
        # Delete results for incomplete tasks (Redundancy Increased)
        sql = text('''DELETE FROM result
                   WHERE result.task_id IN (SELECT id FROM incomplete_tasks);
                   ''')
        self.db.session.execute(sql)
        self.db.session.commit()
        cached_projects.clean_project(project_id)

    def update_priority(self, project_id, priority, filter_args):
        priority = min(1.0, priority)
        priority = max(0.0, priority)
        filters, params = get_task_filters(filter_args)
        sql = text('''
                   WITH to_update AS (
                        SELECT task.id as id,
                        coalesce(ct, 0) as n_task_runs, task.n_answers, ft,
                        priority_0, task.created
                        FROM task LEFT OUTER JOIN
                        (SELECT task_id, CAST(COUNT(id) AS FLOAT) AS ct,
                        MAX(finish_time) as ft FROM task_run
                        WHERE project_id=:project_id GROUP BY task_id) AS log_counts
                        ON task.id=log_counts.task_id
                        WHERE task.project_id=:project_id {}
                   )
                   UPDATE task
                   SET priority_0=:priority
                   WHERE project_id=:project_id AND task.id in (
                        SELECT id FROM to_update);
                   '''.format(filters))
        self.db.session.execute(sql, dict(priority=priority,
                                          project_id=project_id,
                                          **params))
        self.db.session.commit()
        cached_projects.clean_project(project_id)

    def find_duplicate(self, project_id, info):
        """
        Find a task id in the given project with the project info using md5
        index on info column casted as text. Md5 is used to avoid key size
        limitations in BTree indices
        """
        sql = text('''
                   SELECT task.id as task_id
                   FROM task
                   WHERE task.project_id=:project_id
                   AND task.state='ongoing'
                   AND md5(task.info::text)=md5(:info)
                   ''')
        row = self.db.session.execute(sql, dict(project_id=project_id,
                                                info=json.dumps(info))).first()
        if row:
            return row[0]

    def _validate_can_be(self, action, element):
        if not isinstance(element, Task) and not isinstance(element, TaskRun):
            name = element.__class__.__name__
            msg = '%s cannot be %s by %s' % (name, action, self.__class__.__name__)
            raise WrongObjectError(msg)

    def _delete(self, element):
        self._validate_can_be('deleted', element)
        table = element.__class__
        inst = self.db.session.query(table).filter(table.id==element.id).first()
        self.db.session.delete(inst)

    def _delete_zip_files_from_store(self, project):
        from pybossa.core import json_exporter, csv_exporter
        global uploader
        if uploader is None:
            from pybossa.core import uploader
        json_tasks_filename = json_exporter.download_name(project, 'task')
        csv_tasks_filename = csv_exporter.download_name(project, 'task')
        json_taskruns_filename = json_exporter.download_name(project, 'task_run')
        csv_taskruns_filename = csv_exporter.download_name(project, 'task_run')
        container = "user_%s" % project.owner_id
        uploader.delete_file(json_tasks_filename, container)
        uploader.delete_file(csv_tasks_filename, container)
        uploader.delete_file(json_taskruns_filename, container)
        uploader.delete_file(csv_taskruns_filename, container)
