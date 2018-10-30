import logging

import flectra
from flectra.tools.func import lazy_property

from .sessionstore import PostgresSessionStore

_logger = logging.getLogger(__name__)


class RootTkobr(flectra.http.Root):

    @lazy_property
    def session_store(self):
        # Setup http sessions
        _logger.debug('HTTP sessions stored in Postgres')
        return PostgresSessionStore(session_class=flectra.http.FlectraSession)


root = RootTkobr()
flectra.http.root.session_store = root.session_store
