# -*- coding: utf-8 -*-
import psycopg2
import json
import logging
import random
import werkzeug.contrib.sessions
import time

import flectra
from flectra import http
from flectra.tools.func import lazy_property
from flectra.service import security
_logger = logging.getLogger(__name__)

def with_cursor(func):
    def wrapper(self, *args, **kwargs):
        tries = 0
        while True:
            tries += 1
            try:
                return func(self, *args, **kwargs)
            except psycopg2.InterfaceError as e:
                _logger.info("Session in DB connection Retry %s/5" % tries)
                if tries>4:
                    raise e
                self._open_connection()
    return wrapper

class PGSessionStore(werkzeug.contrib.sessions.SessionStore):
    # FIXME This class is NOT thread-safe. Only use in worker mode
    def __init__(self, uri, session_class=None):
        super(PGSessionStore, self).__init__(session_class)
        self._uri = uri
        self._open_connection()
        self._setup_db()

    def __del__(self):
        self._cr.close()

    def _open_connection(self):
        cnx = flectra.sql_db.db_connect(self._uri, allow_uri=True)
        self._cr = cnx.cursor()
        self._cr.autocommit(True)

    @with_cursor
    def _setup_db(self):
        self._cr.execute("""
            CREATE TABLE IF NOT EXISTS http_sessions (
                sid varchar PRIMARY KEY,
                write_date timestamp without time zone NOT NULL,
                payload text NOT NULL
            )
        """)

    @with_cursor
    def save(self, session):
        payload = json.dumps(dict(session))
        self._cr.execute("""
            INSERT INTO http_sessions(sid, write_date, payload)
                 VALUES (%(sid)s, now() at time zone 'UTC', %(payload)s)
            ON CONFLICT (sid)
          DO UPDATE SET payload = %(payload)s,
                        write_date = now() at time zone 'UTC'
        """, dict(sid=session.sid, payload=payload))

    @with_cursor
    def delete(self, session):
        self._cr.execute("DELETE FROM http_sessions WHERE sid=%s", [session.sid])

    @with_cursor
    def get(self, sid):
        self._cr.execute("UPDATE http_sessions SET write_date = now() at time zone 'UTC' WHERE sid=%s", [sid])
        self._cr.execute("SELECT payload FROM http_sessions WHERE sid=%s", [sid])
        try:
            data = json.loads(self._cr.fetchone()[0])
        except Exception:
            return self.new()

        return self.session_class(data, sid, False)

    @with_cursor
    def gc(self):
        self._cr.execute(
            "DELETE FROM http_sessions WHERE now() at time zone 'UTC' - write_date > '7 days'"
        )


def session_gc(session_store):
    """
    Global cleaning of sessions using either the standard way (delete session files),
    Or the DB way.
    """
    if random.random() < 0.001:
        # we keep session one week
        if hasattr(session_store, 'gc'):
            session_store.gc()
            return
        last_week = time.time() - 60*60*24*7
        for fname in os.listdir(session_store.path):
            path = os.path.join(session_store.path, fname)
            try:
                if os.path.getmtime(path) < last_week:
                    os.unlink(path)
            except OSError:
                pass

class Root(http.Root):
    @lazy_property
    def session_store(self):
        """
        Store sessions in DB rather than on FS if parameter permit so
        """
        # Setup http sessions
        session_db = flectra.tools.config.get('session_db')
        if session_db:
            _logger.debug("Sessions in db %s" % session_db)
            return PGSessionStore(session_db, session_class=http.OpenERPSession)
        path = flectra.tools.config.session_dir
        _logger.debug('HTTP sessions stored in: %s', path)
        return werkzeug.contrib.sessions.FilesystemSessionStore(path, session_class=http.OpenERPSession)
                    
def check_session(session, env):
    self = env['res.users'].browse(session.uid)
    expected = str(self._compute_session_token(session.sid))
    if expected and flectra.tools.misc.consteq(expected, session.session_token):
        return True
    self._invalidate_session_cache()
    return False
        
# #Monkey patch of standard methods
_logger.debug("Monkey patching sessions")
http.session_gc = session_gc
http.root = Root()
security.check_session = check_session
