import logging

from plumber import Pipe, Pipeline, precondition, UnmetPrecondition
import transaction

import scieloapitoolbelt


logger = logging.getLogger(__name__)


def attempt_is_valid(data):
    try:
        attempt, _, _, _ = data
    except TypeError:
        attempt = data

    if attempt.is_valid != True:
        logger.debug('Attempt %s does not comply the precondition to be processed by the pipe. Bypassing.' % repr(attempt))
        raise UnmetPrecondition()


class ValidationPipe(Pipe):

    """
    Specialized Pipe which validates the data and notifies the result.
    """
    def __init__(self, notifier):
        self._notifier = notifier

    @precondition(attempt_is_valid)
    def transform(self, item):
        """
        Performs a transformation to one `item` of data iterator.

        `item` is a tuple comprised of instances of models.Attempt, a
        checkin.PackageAnalyzer, a dict of journal and issue data.
        """
        attempt = item[0]
        db_session = item[3]
        logger.debug('%s started processing %s' % (self.__class__.__name__, attempt))

        result_status, result_description = self.validate(item)

        savepoint = transaction.savepoint()
        try:
            self._notifier(attempt, db_session).tell(result_description, result_status, label=self._stage_)
        except Exception as e:
            savepoint.rollback()
            logger.error('An exception was raised during %s stage: %s' % (self._stage_, e))
            raise

        return item

    def validate(self, item):
        """
        Performs the validation of `item`.

        `item` is a tuple comprised of instances of models.Attempt, a
        checkin.PackageAnalyzer, a dict of journal and issue data.
        """
        raise NotImplementedError()

