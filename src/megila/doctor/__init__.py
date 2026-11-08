"""Machine check for the Megila CLI (``megila doctor``).

The check reads the local ffmpeg build, CPU, RAM, free disk, GPU, and
temperature sensors. It suggests a machine profile (``leve``, ``padrao``,
or ``forte``) and warns when a backup destination is on the same disk as
the source. It does not start a job and it does not change the quality
profile.
"""

from megila.doctor.collect import collect_report, run_doctor
from megila.doctor.facts import DoctorReport
from megila.doctor.render import render_json, render_plain

__all__ = [
    "DoctorReport",
    "collect_report",
    "render_json",
    "render_plain",
    "run_doctor",
]
