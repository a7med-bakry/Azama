"""Durable records. Only the server can read sessions or write queue state."""
import json
import sqlite3
from pathlib import Path
import requests


class StorageError(Exception):
    pass


class SQLiteStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL)')

    def connection(self):
        return sqlite3.connect(self.path, timeout=15)

    def get(self, kind, key):
        with self.connection() as db:
            row = db.execute('SELECT payload FROM records WHERE id=? AND kind=?', (key, kind)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind):
        with self.connection() as db:
            rows = db.execute('SELECT payload FROM records WHERE kind=? ORDER BY rowid DESC', (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put(self, kind, record):
        with self.connection() as db:
            db.execute('INSERT INTO records VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, status=excluded.status',
                       (record['id'], kind, json.dumps(record), record['status']))

    def delete(self, kind, key):
        with self.connection() as db:
            db.execute('DELETE FROM records WHERE id=? AND kind=?', (key, kind))

    def claim(self, job):
        with self.connection() as db:
            result = db.execute('UPDATE records SET status=?, payload=? WHERE id=? AND kind=? AND status=?',
                                ('running', json.dumps(job), job['id'], 'job', 'queued'))
            return result.rowcount == 1

    def ping(self):
        with self.connection() as db:
            db.execute('SELECT 1').fetchone()


class SupabaseStore:
    def __init__(self, url, key):
        self.url = url + '/rest/v1/insta_records'
        self.headers = {'apikey': key, 'Authorization': 'Bearer ' + key}

    def request(self, method, params=None, body=None, prefer=None):
        try:
            headers = dict(self.headers)
            if prefer:
                headers['Prefer'] = prefer
            result = requests.request(method, self.url, params=params, json=body, headers=headers, timeout=15)
            result.raise_for_status()
            return result.json() if result.content else None
        except (requests.RequestException, ValueError):
            # Never expose provider bodies, URLs, keys or encrypted account payloads.
            raise StorageError('Database unavailable') from None

    def get(self, kind, key):
        rows = self.request('GET', {'kind': 'eq.' + kind, 'id': 'eq.' + key, 'select': 'payload'})
        return rows[0]['payload'] if rows else None

    def list(self, kind):
        records = []
        while True:
            rows = self.request('GET', {'kind': 'eq.' + kind, 'select': 'payload', 'order': 'created_at.desc,id.desc', 'limit': '500', 'offset': str(len(records))})
            records.extend(row['payload'] for row in rows)
            if len(rows) < 500:
                return records

    def put(self, kind, record):
        self.request('POST', {'on_conflict': 'id'}, {'id': record['id'], 'kind': kind, 'payload': record, 'status': record['status']}, 'resolution=merge-duplicates')

    def delete(self, kind, key):
        self.request('DELETE', {'kind': 'eq.' + kind, 'id': 'eq.' + key})

    def claim(self, job):
        rows = self.request('PATCH', {'id': 'eq.' + job['id'], 'kind': 'eq.job', 'status': 'eq.queued'},
                            {'payload': job, 'status': 'running'}, 'return=representation')
        return bool(rows)

    def ping(self):
        self.request('GET', {'select': 'id', 'limit': '1'})
