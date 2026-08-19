import json
import logging
from logging.config import dictConfig
import logging.handlers
import os
import ssl
import sys
import traceback
import urllib.request
import uuid

from .utils import sw_version, sw_version_is_stable


# markdown debug is also considered useless
logging.getLogger('MARKDOWN').setLevel(logging.INFO)
# asyncio runs in debug mode but we do not need INFO/DEBUG
logging.getLogger('asyncio').setLevel(logging.WARN)
# We dont need internal aiohttp debug logging
logging.getLogger('aiohttp.internal').setLevel(logging.WARN)
# We dont need internal botocore debug logging
logging.getLogger('botocore').setLevel(logging.WARN)
# we dont need ws4py close debug messages
logging.getLogger('ws4py').setLevel(logging.WARN)
# we dont need GitPython debug messages (used in iocage)
logging.getLogger('git.cmd').setLevel(logging.WARN)
# issues garbage warnings
logging.getLogger('googleapiclient').setLevel(logging.ERROR)
# registered 'pbkdf2_sha256' handler: <class 'passlib.handlers.pbkdf2.pbkdf2_sha256'>
logging.getLogger('passlib.registry').setLevel(logging.INFO)

# Куда уходят отчёты о падениях. Свой приёмник: он принимает трассировку и
# версию, складывает в файл и больше ничего не делает. Прежний адрес вёл в
# Sentry iXsystems — см. описание класса ниже.
CRASH_REPORT_URL = 'https://crash.bsdnas.com/crash/v1/report'
CRASH_REPORT_TIMEOUT = 10
# Идентификатор установки: случайный, заводится один раз и живёт в /data
# (переживает обновление, не переживает переустановку). Нужен ровно затем,
# чтобы отличить десять отчётов с одной машины от десяти машин; кто владелец
# машины, по нему не узнать.
CRASH_INSTALL_ID_FILE = '/data/.crash_install_id'

LOGFILE = '/var/log/middlewared.log'
ZETTAREPL_LOGFILE = '/var/log/zettarepl.log'
FAILOVER_LOGFILE = '/root/syslog/failover.log'
logging.TRACE = 6


def trace(self, message, *args, **kws):
    if self.isEnabledFor(logging.TRACE):
        self._log(logging.TRACE, message, args, **kws)


logging.addLevelName(logging.TRACE, "TRACE")
logging.Logger.trace = trace


class CrashReporting(object):
    enabled_in_settings = False

    """
    Crash reporting.

    Upstream shipped this wired to a Sentry instance run by iXsystems, on by
    default, sending the tail of the logs — 10 KB of whatever the machine was
    doing — to a third party. That is gone. What is sent now, and only when
    reporting is enabled:

        the traceback, the product version, and a random installation id

    No log contents, no hostname, no addresses, no configuration. The
    installation id is generated once, kept in /data, and exists only to tell
    ten crashes from one machine apart from ten machines; it says nothing
    about who owns it. The report is one POST with a short timeout: a
    collector that is down or slow must never hold up the middleware.
    """

    def __init__(self):
        if sw_version_is_stable():
            self.sentinel_file_path = '/tmp/.crashreporting_disabled'
        else:
            self.sentinel_file_path = '/data/.crashreporting_disabled'
        self.logger = logging.getLogger('middlewared.logger.CrashReporting')

    def is_disabled(self):
        """
        Check the existence of sentinel file and its absolute path
        against STABLE and DEVELOPMENT branches.

        Returns:
            bool: True if crash reporting is disabled, False otherwise.
        """
        # Allow report to be disabled via sentinel file or environment var,
        # if FreeNAS current train is STABLE, the sentinel file path will be /tmp/,
        # otherwise it's path will be /data/ and can be persistent.

        if not self.enabled_in_settings:
            return True

        if os.path.exists(self.sentinel_file_path) or 'CRASHREPORTING_DISABLED' in os.environ:
            return True

        if os.stat(__file__).st_dev != os.stat('/').st_dev:
            return True

        return False

    def install_id(self):
        """Random id for this installation, created on first use."""
        try:
            with open(CRASH_INSTALL_ID_FILE) as fh:
                value = fh.read().strip()
            if len(value) >= 16:
                return value
        except OSError:
            pass
        value = uuid.uuid4().hex
        try:
            with open(CRASH_INSTALL_ID_FILE, 'w') as fh:
                fh.write(value + '\n')
            os.chmod(CRASH_INSTALL_ID_FILE, 0o600)
        except OSError:
            self.logger.debug('Cannot store the installation id', exc_info=True)
        return value

    def report(self, exc_info, log_files):
        """Record the crash locally and, if enabled, send it to our collector.

        Args:
            exc_info (tuple): same as sys.exc_info().
            log_files (tuple): kept for the caller's signature; deliberately
                unused — log contents are not sent anywhere.
        """
        # The local log gets the crash whatever the setting says: it is the
        # machine's own record, and it never leaves the machine.
        self.logger.error('Unhandled exception', exc_info=exc_info)

        if self.is_disabled():
            return

        report = {
            'schema': 1,
            'version': sw_version(),
            'install_id': self.install_id(),
            'traceback': ''.join(traceback.format_exception(*exc_info))[-16384:],
        }
        try:
            request = urllib.request.Request(
                CRASH_REPORT_URL,
                data=json.dumps(report).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(
                request, timeout=CRASH_REPORT_TIMEOUT, context=ssl.create_default_context()
            ) as response:
                self.logger.debug('Crash report sent, collector said %s', response.status)
        except Exception:
            # A collector that is unreachable is not the user's problem and
            # must not turn one crash into two.
            self.logger.debug('Could not send the crash report', exc_info=True)


class LoggerFormatter(logging.Formatter):
    """Format the console log messages"""

    CONSOLE_COLOR_FORMATTER = {
        'YELLOW': '\033[1;33m',  # (warning)
        'GREEN': '\033[1;32m',  # (info)
        'RED': '\033[1;31m',  # (error)
        'HIGHRED': '\033[1;41m',  # (critical)
        'RESET': '\033[1;m',  # Reset
    }
    LOGGING_LEVEL = {
        'CRITICAL': 50,
        'ERROR': 40,
        'WARNING': 30,
        'INFO': 20,
        'DEBUG': 10,
        'NOTSET': 0
    }

    def format(self, record):
        """Set the color based on the log level.

            Returns:
                logging.Formatter class.
        """

        if record.levelno == self.LOGGING_LEVEL['CRITICAL']:
            color_start = self.CONSOLE_COLOR_FORMATTER['HIGHRED']
        elif record.levelno == self.LOGGING_LEVEL['ERROR']:
            color_start = self.CONSOLE_COLOR_FORMATTER['HIGHRED']
        elif record.levelno == self.LOGGING_LEVEL['WARNING']:
            color_start = self.CONSOLE_COLOR_FORMATTER['RED']
        elif record.levelno == self.LOGGING_LEVEL['INFO']:
            color_start = self.CONSOLE_COLOR_FORMATTER['GREEN']
        elif record.levelno == self.LOGGING_LEVEL['DEBUG']:
            color_start = self.CONSOLE_COLOR_FORMATTER['YELLOW']
        else:
            color_start = self.CONSOLE_COLOR_FORMATTER['RESET']

        color_reset = self.CONSOLE_COLOR_FORMATTER['RESET']

        record.levelname = color_start + record.levelname + color_reset

        return logging.Formatter.format(self, record)


class LoggerStream(object):

    def __init__(self, logger):
        self.logger = logger
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.debug(line.rstrip())


class ErrorProneRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def handleError(self, record):
        try:
            super().handleError(record)
        except ValueError:
            # sys.stderr can be closed by core.reconfigure_logging which leads to
            # ValueError: I/O operation on closed file. raised on every operation that
            # involves logging
            pass

    def doRollover(self):
        super().doRollover()
        # We must reconfigure stderr/stdout streams after rollover
        reconfigure_logging()


class Logger(object):
    """Pseudo-Class for Logger - Wrapper for logging module"""
    def __init__(
        self, application_name, debug_level=None,
        log_format='[%(asctime)s] (%(levelname)s) %(name)s.%(funcName)s():%(lineno)d - %(message)s'
    ):
        self.application_name = application_name
        self.debug_level = debug_level or 'DEBUG'
        self.log_format = log_format

        self.DEFAULT_LOGGING = {
            'version': 1,
            'disable_existing_loggers': False,
            'loggers': {
                '': {
                    'level': 'NOTSET',
                    'handlers': ['file'],
                },
                'zettarepl': {
                    'level': 'NOTSET',
                    'handlers': ['zettarepl_file'],
                    'propagate': False,
                },
                'failover': {
                    'level': 'NOTSET',
                    'handlers': ['failover_file', 'sys-logger'],
                    'propagate': False,
                },
            },
            'handlers': {
                'sys-logger': {
                    'level': 'DEBUG',
                    'class': 'logging.handlers.SysLogHandler',
                    'address': '/var/run/log',
                    'formatter': 'file',
                },
                'file': {
                    'level': 'DEBUG',
                    'class': 'middlewared.logger.ErrorProneRotatingFileHandler',
                    'filename': LOGFILE,
                    'mode': 'a',
                    'maxBytes': 10485760,
                    'backupCount': 5,
                    'encoding': 'utf-8',
                    'formatter': 'file',
                },
                'zettarepl_file': {
                    'level': 'DEBUG',
                    'class': 'middlewared.logger.ErrorProneRotatingFileHandler',
                    'filename': ZETTAREPL_LOGFILE,
                    'mode': 'a',
                    'maxBytes': 10485760,
                    'backupCount': 5,
                    'encoding': 'utf-8',
                    'formatter': 'zettarepl_file',
                },
                'failover_file': {
                    'level': 'DEBUG',
                    'class': 'middlewared.logger.ErrorProneRotatingFileHandler',
                    'filename': FAILOVER_LOGFILE,
                    'mode': 'a',
                    'maxBytes': 10485760,
                    'backupCount': 5,
                    'encoding': 'utf-8',
                    'formatter': 'file',
                },
            },
            'formatters': {
                'file': {
                    'format': self.log_format,
                    'datefmt': '%Y/%m/%d %H:%M:%S',
                },
                'zettarepl_file': {
                    'format': '[%(asctime)s] %(levelname)-8s [%(threadName)s] [%(name)s] %(message)s',
                    'datefmt': '%Y/%m/%d %H:%M:%S',
                },
            },
        }

    def getLogger(self):
        return logging.getLogger(self.application_name)

    def stream(self):
        for handler in logging.root.handlers:
            if isinstance(handler, ErrorProneRotatingFileHandler):
                return handler.stream

    def _set_output_file(self):
        """Set the output format for file log."""
        try:
            os.makedirs(os.path.dirname(FAILOVER_LOGFILE), mode=0o755, exist_ok=True)
            dictConfig(self.DEFAULT_LOGGING)
        except Exception:
            # If something happens during system dataset reconfiguration, we have the chance of not having
            # /var/log present leaving us with "ValueError: Unable to configure handler 'file':
            # [Errno 2] No such file or directory: '/var/log/middlewared.log'"
            # crashing the middleware during startup
            pass
        # Make sure log file is not readable by everybody.
        # umask could be another approach but chmod was chosen so
        # it affects existing installs.
        try:
            os.chmod(LOGFILE, 0o640)
        except OSError:
            pass
        try:
            os.chmod(ZETTAREPL_LOGFILE, 0o640)
        except OSError:
            pass

    def _set_output_console(self):
        """Set the output format for console."""

        console_handler = logging.StreamHandler()
        logging.root.setLevel(getattr(logging, self.debug_level))
        time_format = "%Y/%m/%d %H:%M:%S"
        console_handler.setFormatter(LoggerFormatter(self.log_format, datefmt=time_format))

        logging.root.addHandler(console_handler)

    def configure_logging(self, output_option='file'):
        """Configure the log output to file or console.

            Args:
                    output_option (str): Default is `file`, can be set to `console`.
        """

        if output_option.lower() == 'console':
            self._set_output_console()
        else:
            self._set_output_file()

        logging.root.setLevel(getattr(logging, self.debug_level))


def setup_logging(name, debug_level, log_handler):
    _logger = Logger(name, debug_level)
    _logger.getLogger()

    if 'file' in log_handler:
        _logger.configure_logging('file')
        stream = _logger.stream()
        if stream is not None:
            sys.stdout = sys.stderr = stream
    elif 'console' in log_handler:
        _logger.configure_logging('console')
    else:
        _logger.configure_logging('file')


def reconfigure_logging(handler_name='file'):
    handler = logging._handlers.get(handler_name)
    if handler:
        stream = handler.stream
        handler.stream = handler._open()
        if handler_name == 'file':
            # We want to reassign stdout/stderr if its not the default one or closed
            # which will happen on log file rotation.
            try:
                if sys.stdout.fileno() != 1 or sys.stderr.fileno() != 2:
                    raise ValueError()
            except ValueError:
                # ValueError can be raise if file handler is closed
                sys.stdout = handler.stream
                sys.stderr = handler.stream
        try:
            stream.close()
        except Exception:
            pass
