"""Durable, idempotent device completion ingestion; no model import at module load."""
import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone

CHINA = timezone(timedelta(hours=8))
FIELD_LIMITS = {'event_id': 128, 'device_id': 128, 'task_id': 128,
                'title': 384, 'body': 8192, 'note': 4096}
EVENT_FIELDS = frozenset((*FIELD_LIMITS, 'scheduled_at', 'completed_at'))


class EventConflict(ValueError):
    """An event identifier was already persisted with different content."""


def validate_event(value, device):
    if not isinstance(value, dict) or set(value) != EVENT_FIELDS:
        raise ValueError('Expected the fixed completion event schema')
    for key, limit in FIELD_LIMITS.items():
        item = value[key]
        if not isinstance(item, str) or (key not in ('note', 'body') and not item.strip()):
            raise ValueError('Invalid text field: ' + key)
        try:
            size = len(item.encode('utf-8', errors='strict'))
        except UnicodeError:
            raise ValueError('Invalid UTF-8 text') from None
        if size > limit or '\x00' in item:
            raise ValueError('Text exceeds allowed bounds: ' + key)
    if value['device_id'] != device:
        raise ValueError('Device identity mismatch')
    for key in ('scheduled_at', 'completed_at'):
        stamp = value[key]
        if key == 'scheduled_at' and stamp is None:
            continue
        if type(stamp) is not int or stamp < (1 if key == 'completed_at' else 0):
            raise ValueError('Expected UTC epoch seconds: ' + key)
        try:
            datetime.fromtimestamp(stamp, CHINA)
        except (ValueError, OverflowError, OSError):
            raise ValueError('Invalid timestamp: ' + key) from None
    return dict(value)


class DeviceArchive:
    def __init__(self, *, store=None, archive_root=None):
        self._store = store
        self.archive_root = archive_root
        self._initialization = threading.Lock()

    @property
    def store(self):
        # Called only by the request worker; models never block dashboard startup.
        with self._initialization:
            if self._store is None:
                from archive_store import ArchiveStore
                self._store = ArchiveStore() if self.archive_root is None else ArchiveStore(self.archive_root)
        return self._store

    def receive(self, value, device):
        event = validate_event(value, device)
        canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        identity = json.dumps([device, event['event_id']], ensure_ascii=False, separators=(',', ':'))
        record_id = 'device-journal-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()
        store = self.store

        def persisted():
            try:
                record = store.get(record_id)
            except KeyError:
                return None
            # User edits may replace fields/body; the immutable first history
            # revision is the original ingestion proof, never the editable view.
            history = store.history(record_id)
            original = history[0] if history else {}
            fields = original.get('fields', {})
            if (record.get('category') != 'journal' or original.get('category') != 'journal'
                    or original.get('id') != record_id or original.get('revision') != 1
                    or fields.get('event_payload_sha256') != digest
                    or fields.get('event_id') != event['event_id'] or fields.get('device_id') != device):
                raise EventConflict('Event identifier already has different content')
            return {'ok': True, 'event_id': event['event_id'], 'record_id': record_id,
                    'index_status': record.get('index_status', 'pending')}

        # The first immutable history revision is the durable dedupe relation:
        # it commits with the original record, without a second dedupe commit. ArchiveStore's reentrant FileLock also guards
        # other processes and its save keeps the normal history/index path.
        with store.lock:
            previous = persisted()
            if previous is not None:
                return previous
            fields = {key: event[key] for key in ('event_id', 'device_id', 'task_id',
                       'scheduled_at', 'completed_at', 'note', 'body')}
            fields['event_payload_sha256'] = digest
            record = {'id': record_id, 'category': 'journal', 'title': event['title'],
                      'body': event['body'] if event['body'].strip() else event['title'], 'fields': fields,
                      'date': datetime.fromtimestamp(event['completed_at'], CHINA).date().isoformat(),
                      'tags': ['device-completion'], 'links': []}
            try:
                store.save(record, expected_revision=0)
            except Exception:
                # save may commit the original then lose its indexing/response.
                # Acknowledge only if a fresh read proves the record is durable.
                recovered = persisted()
                if recovered is not None:
                    return recovered
                raise
            result = persisted()
            if result is None:
                raise OSError('Archive save did not persist the completion')
            return result
