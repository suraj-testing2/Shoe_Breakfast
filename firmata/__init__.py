"""Provides an API wrapper around the Firmata wire protocol.

There are two major pieces to the firmata module. When FirmataInit() is called, a thread is spun up to handle serial
port IO. Its sole function is to read bytes into the read queue and write bytes from the write queue. These queues are
then used by the main body of code to respond to API calls made by the host application.

The API presented to the host program is encapsulated in the `Board` class, instances of which are obtained by calling
the previously mentioned `FirmataInit()` function. You can create as many Board classes as you wish, but you will not
go to space today if you create more than on on the same serial port.
"""

import collections
from Queue import Queue, Empty
import sys
import threading

from firmata.constants import *
from firmata.io import SerialPort


class Board(threading.Thread):
  def __init__(self, port, baud, log_to_file=None, start_serial=False):
    """Board object constructor. Should not be called directly.

    Args:
      port: The serial port to use. Expressed as either a string or an integer (see pyserial docs for more info.)
      baud: A number representing the baud rate to use for serial communication.
      log_to_file: A string specifying the file to log serial events to, or None (the default) for no logging.
      start_serial: If True, starts the serial IO thread right away. Default: False.
    """
    self.port = SerialPort(port=port, baud=baud, log_to_file=log_to_file, start_serial=start_serial)
    self.shutdown = False
    self.firmware_version = 'Unknown'
    self.firmware_name = 'Unknown'
    self.errors = []
    self.analog_channels = []
    self.pin_config = []
    self._listeners = collections.defaultdict(list)
    self._listeners_lock = threading.Lock()

  def StartCommunications(self):
    """Starts all the threads needed to communicate with the physical board."""
    self.port.StartCommunications()
    self.shutdown = False
    self.start()

  def StopCommunications(self):
    """Stops communication with the board, and returns only after all communication has ceased."""
    self.port.StopCommunications()
    self.shutdown = True
    self.join()

  def __del__(self):
    self.port.StopCommunications()

  def AddListener(self, token_type, listener):
    """Add a callable to be called the next time a particular token_type is received.

    Args:
      token_type: A string. The type of token to listen for.
      listener: A callable taking one argument (a token), which returns True if normal dispatch should be aborted, or
          False otherwise. The callable will be called at most once.
    """
    self._listeners_lock.acquire()
    self._listeners[token_type].append(listener)
    self._listeners_lock.release()

  def DispatchToken(self, token):
    """Given a token, mutates Board state and calls listeners as appropriate.

    Args:
      token: A dictionary. The token to dispatch.
    Returns:
      A boolean indicating success (True) or failure (False). On failure, an error will have been appended to the error
      queue.
    """
    token_type = token['token']
    self._listeners_lock.acquire()
    my_listeners = self._listeners.get(token_type, [])
    del self._listeners[token_type]
    self._listeners_lock.release()
    abort_regular_execution = False
    for l in my_listeners:
      if l(token):
        abort_regular_execution = True
    if abort_regular_execution:
      return True
    if token_type == 'ERROR':
      self.errors.append(token['message'])
      return True
    if token_type == 'RESERVED_COMMAND':
      self.errors.append('Unable to parse a reserved command: %s' % (repr(token)))
      return False
    if token_type == 'REPORT_FIRMWARE':
      self.firmware_version = '%s.%s' % (token[major], token[minor])
      self.firmware_name = token['name']
      return True
    if token_type == 'ANALOG_MAPPING_RESPONSE':
      self.analog_channels = token['channels']
      return True
    if token_type == 'CAPABILITY_RESPONSE':
      self.pin_config = token['pins']
      self.pin_state = collections.defaultdict(lambda: False)
      return True
    if token_type == 'ANALOG_MESSAGE':
      self.pin_state['A%s' % analog_pin] = token['value']
      return True
    if token_type == 'DIGITAL_MESSAGE':
      self.pin_state[token['pin']] = token['value']
      return True
    if token_type == 'PROTOCOL_VERSION':
      self.firmware_version = '%s.%s' % (token[major], token[minor])
      return True
    if token_type == 'PIN_STATE_RESPONSE':
      if token['mode'] == MODE_ANALOG:
        token['pin'] = 'A%s' % token['pin']
      self.pin_state[token['pin']] = token['data']
      return True
    self.errors.append('Unable to dispatch token: %s' % (repr(token)))
    return False

  def run(self):
    """Reads tokens as they come in, and dispatches them appropriately. If an error occurs, the thread terminates."""
    while not self.shutdown:
      token = None
      try:
        token = self.port.reader.q.get(timeout=0.2)
      except Empty:
        continue
      if not token or not self.DispatchToken(token):
        break


def FirmataInit(port, baud=57600, log_to_file=None):
  """Instantiate a `Board` object for a given serial port.

  Args:
    port: The serial port to use. Expressed as either a string or an integer (see pyserial docs for more info.)
    baud: A number representing the baud rate to use for serial communication.
    log_to_file: A string specifying the file to log serial events to, or None (the default) for no logging.

  Returns:
    A Board object which implements the firmata protocol over the specified serial port.
  """
  return Board(port, baud, log_to_file=log_to_file, start_serial=True)

__all__ = ['FirmataInit', 'Board', 'SerialPort'] + CONST_R.values()
