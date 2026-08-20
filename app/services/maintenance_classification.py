"""Planned vs unplanned classification for maintenance events.

One definition, shared, so the downtime split and the cost split on the admin
dashboard can never disagree with each other.

Why this exists
---------------
Planned work cannot be defined as ``event_type = 'preventive'`` alone. That
single value is used by **zero** rows in this database: the
``maintenance_event_type`` enum declares eight values but only four are ever
written (``scheduled_service``, ``replacement``, ``repair``, ``breakdown``).
Defining it that way gives a downtime chart of 0 planned hours against ~20,000
unplanned, a fleet that reads as 100% reactive, and a cost chart whose
"Estimated" series is a flat zero line.

Taxonomy
--------
Follows the EN 13306 / SMRP split between *preventive* (work decided before a
fault occurs) and *corrective* (work triggered by a fault):

``inspection``, ``scheduled_service``, ``preventive``
    Planned by definition, the work was decided ahead of any failure.

``breakdown``, ``corrective``, ``repair``
    Unplanned by definition, fault-driven. ``repair`` counts here even when a
    slot was booked for it: booking a time to fix something already broken does
    not make the failure planned.

``replacement``, ``other``
    Genuinely ambiguous, a component swap can be a scheduled life-cycle
    replacement or a failure replacement. The presence of a ``scheduled_date``
    decides it, which is the usual CMMS discriminator: work raised in advance
    is planned, work raised reactively is not.

Every declared enum value is covered exactly once. Values outside the enum
(should any appear) fall through to unplanned, which is the conservative
direction, it over-reports reactive work rather than flattering the numbers.

Against current data this yields 87.3% of events / 71.4% of downtime hours as
planned, against the >=90% PM-coverage target recorded in
``app/kb/kb_documents.py``.

Note ``app/agents/report_agents.py`` and ``app/kb/kb_annotator.py`` compute a
separate "PM ratio" using ``preventive + scheduled``. That is a different
metric with its own definition and is deliberately left alone here; if the two
are ever meant to be the same number, they should both move onto this module.
"""

from __future__ import annotations

from sqlalchemy import and_, case, or_

from ..models import MaintenanceEvent

#: Work decided before any fault, planned regardless of scheduling metadata.
PLANNED_EVENT_TYPES: tuple[str, ...] = ("inspection", "scheduled_service", "preventive")

#: Fault-driven work, unplanned even if a repair slot was booked afterwards.
UNPLANNED_EVENT_TYPES: tuple[str, ...] = ("breakdown", "corrective", "repair")

#: Could be either; ``scheduled_date`` decides.
SCHEDULE_DECIDES_EVENT_TYPES: tuple[str, ...] = ("replacement", "other")


def is_planned():
    """SQLAlchemy boolean expression, true when the event is planned work."""
    return or_(
        MaintenanceEvent.event_type.in_(PLANNED_EVENT_TYPES),
        and_(
            MaintenanceEvent.event_type.in_(SCHEDULE_DECIDES_EVENT_TYPES),
            MaintenanceEvent.scheduled_date.isnot(None),
        ),
    )


def planned_value(column, default=0):
    """``column`` when the event is planned, else ``default``.

    Use inside ``func.sum(...)`` to total only the planned share of a measure.
    """
    return case((is_planned(), column), else_=default)


def unplanned_value(column, default=0):
    """``column`` when the event is unplanned, else ``default``."""
    return case((is_planned(), default), else_=column)
