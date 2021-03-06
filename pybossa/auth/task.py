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

from werkzeug.exceptions import NotFound


class TaskAuth(object):
    _specific_actions = []

    def __init__(self, project_repo, result_repo):
        self.project_repo = project_repo
        self.result_repo = result_repo

    @property
    def specific_actions(self):
        return self._specific_actions

    def can(self, user, action, task=None):
        action = ''.join(['_', action])
        return getattr(self, action)(user, task)

    def _create(self, user, task):
        return self._only_admin_or_subadminowners(user, task)

    def _read(self, user, task=None):
        return user.is_authenticated

    def _update(self, user, task):
        return self._only_admin_or_subadminowners(user, task)

    def _delete(self, user, task):
        if user.is_authenticated and user.admin:
            return True
        if self.result_repo.get_by(task_id=task.id,
                                   project_id=task.project_id):
            return False
        return self._only_admin_or_subadminowners(user, task)

    def _only_admin_or_subadminowners(self, user, task):
        if not user.is_anonymous:
            project = self.project_repo.get(task.project_id)
            if project is None:
                raise NotFound("Invalid project ID")
            return user.admin or (user.subadmin and user.id in project.owners_ids)
        return False
