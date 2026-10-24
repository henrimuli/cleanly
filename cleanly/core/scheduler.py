# SPDX-License-Identifier: GPL-3.0-or-later
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""
Schedule background scans with the Windows Task Scheduler

The task runs 'Cleanly.exe --background-scan' as the signed-in user, so
it needs no administrator rights and can show notifications. Nothing
stays running between scans.
"""

import datetime
import logging
import os
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

from cleanly import APP_NAME

logger = logging.getLogger(__name__)

TASK_NAME = 'Cleanly Background Scan'
BACKGROUND_ARG = '--background-scan'

_WEEKDAY_ELEMENTS = {
    'MON': 'Monday', 'TUE': 'Tuesday', 'WED': 'Wednesday',
    'THU': 'Thursday', 'FRI': 'Friday', 'SAT': 'Saturday', 'SUN': 'Sunday',
}


def task_command():
    """(command, arguments, working directory) that start a background scan"""
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        return exe, BACKGROUND_ARG, os.path.dirname(exe)
    # From source: pythonw.exe opens no console window
    python = sys.executable
    pythonw = os.path.join(os.path.dirname(python), 'pythonw.exe')
    if os.path.exists(pythonw):
        python = pythonw
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return python, '-m cleanly ' + BACKGROUND_ARG, repo_root


def build_task_xml(schedule, command, today=None):
    """Task Scheduler XML for the schedule from cleanly.core.settings

    StartWhenAvailable makes a missed run (PC off or asleep) happen at
    the next chance. The scan does not start on battery power.
    """
    today = today or datetime.date.today()
    start = '%sT%s:00' % (today.isoformat(), schedule['time'])
    if schedule['frequency'] == 'daily':
        when = '<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>'
    elif schedule['frequency'] == 'weekly':
        day = _WEEKDAY_ELEMENTS[schedule['weekday']]
        when = ('<ScheduleByWeek><DaysOfWeek><%s /></DaysOfWeek>'
                '<WeeksInterval>1</WeeksInterval></ScheduleByWeek>' % day)
    else:
        raise ValueError('No task for frequency %s' % schedule['frequency'])
    exe, arguments, workdir = command
    return '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      {when}
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''.format(description=escape('%s scans for junk files in the background.' % APP_NAME),
           start=start, when=when, exe=escape(exe),
           arguments=escape(arguments), workdir=escape(workdir))


def _schtasks(*args):
    """Run schtasks.exe without a console window; return CompletedProcess"""
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(['schtasks', *args], capture_output=True,
                          text=True, check=False, **kwargs)


def apply(schedule):
    """Create, update or remove the task to match the schedule

    Raises RuntimeError with schtasks' message when it fails.
    """
    if os.name != 'nt':
        raise RuntimeError('Scheduled scans need Windows')
    if schedule['frequency'] == 'off':
        remove()
        return
    xml = build_task_xml(schedule, task_command())
    fd, path = tempfile.mkstemp(suffix='.xml', prefix='cleanly-task-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-16') as f:
            f.write(xml)
        result = _schtasks('/Create', '/TN', TASK_NAME, '/XML', path, '/F')
    finally:
        os.remove(path)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()
                           or 'Could not create the scheduled task')


def remove():
    """Remove the task if it exists"""
    if os.name != 'nt' or not is_installed():
        return
    result = _schtasks('/Delete', '/TN', TASK_NAME, '/F')
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()
                           or 'Could not remove the scheduled task')


def is_installed():
    if os.name != 'nt':
        return False
    return _schtasks('/Query', '/TN', TASK_NAME).returncode == 0
