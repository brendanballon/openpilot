#!/usr/bin/env python
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = 'true'
os.environ['SDL_VIDEODRIVER'] = 'dummy'

import argparse
import threading
import pygame

from rich.console import Console
from rich.live import Live

import cereal.messaging as messaging
from openpilot.common.realtime import Ratekeeper
from openpilot.common.numpy_fast import interp, clip
from openpilot.common.params import Params
from openpilot.tools.lib.kbhit import KBHit

pygame.init()

console = Console()

class Keyboard:
  def __init__(self):
    self.kb = KBHit()
    self.axis_increment = 0.05  # 5% of full actuation each key press
    self.axes_map = {'w': 'gb', 's': 'gb',
                     'a': 'steer', 'd': 'steer'}
    self.axes_values = {'gb': 0., 'steer': 0.}
    self.axes_order = ['gb', 'steer']
    self.cancel = False

  def update(self):
    key = self.kb.getch().lower()
    self.cancel = False
    if key == 'r':
      self.axes_values = {ax: 0. for ax in self.axes_values}
    elif key == 'c':
      self.cancel = True
    elif key in self.axes_map:
      axis = self.axes_map[key]
      incr = self.axis_increment if key in ['w', 'a'] else -self.axis_increment
      self.axes_values[axis] = clip(self.axes_values[axis] + incr, -1, 1)
    else:
      return False
    return True


class Joystick:
    def __init__(self, gamepad=False):
        self.joystick = pygame.joystick.Joystick(0)  # Assume one joystick connected
        self.joystick.init()

        # Define mappings for axes and buttons
        self.accel_axis = 1  # Example mapping, update as needed
        self.steer_axis = 2  # Example mapping, update as needed
        self.cancel_button = 0  # Example mapping, update as needed

        self.axes_values = {self.accel_axis: 0., self.steer_axis: 0.}
        self.axes_order = [self.accel_axis, self.steer_axis]
        self.cancel = False

    def update(self):
        pygame.event.pump()  # Process event queue
        for event in pygame.event.get():
            if event.type == pygame.JOYAXISMOTION:
                axis = event.axis
                if axis in self.axes_values:
                    norm = -interp(event.value, [-1., 1.], [-1., 1.])
                    self.axes_values[axis] = norm if abs(norm) > 0.05 else 0.

            elif event.type == pygame.JOYBUTTONDOWN:
                if event.button == self.cancel_button:
                    print('Cancel')
                    self.cancel = (event.type == pygame.JOYBUTTONDOWN)

        return True

def send_thread(joystick):
  joystick_sock = messaging.pub_sock('testJoystick')
  rk = Ratekeeper(100, print_delay_threshold=None)
  with Live(console=console, refresh_per_second=10) as live:
    while 1:
      dat = messaging.new_message('testJoystick')
      dat.testJoystick.axes = [joystick.axes_values[a] for a in joystick.axes_order]
      dat.testJoystick.buttons = [joystick.cancel]
      joystick_sock.send(dat.to_bytes())
      # print('\n' + ', '.join(f'{name}: {round(v, 3)}' for name, v in joystick.axes_values.items()))

      output = ', '.join(f'{name}: {round(v, 3)}' for name, v in joystick.axes_values.items())
      live.update(output, refresh=True)

      if "WEB" in os.environ:
        import requests
        requests.get("http://"+os.environ["WEB"]+":5000/control/%f/%f" % tuple([joystick.axes_values[a] for a in joystick.axes_order][::-1]), timeout=None)
      rk.keep_time()

def joystick_thread(joystick):
  Params().put_bool('JoystickDebugMode', True)
  threading.Thread(target=send_thread, args=(joystick,), daemon=True).start()
  try:
    while True:
      joystick.update()
  except KeyboardInterrupt:
    # Perform any cleanup here if necessary
    return

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Publishes events from your joystick to control your car.\n' +
                                               'openpilot must be offroad before starting joysticked.',
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('--keyboard', action='store_true', help='Use your keyboard instead of a joystick')
  parser.add_argument('--gamepad', action='store_true', help='Use gamepad configuration instead of joystick')
  args = parser.parse_args()

  if not Params().get_bool("IsOffroad") and "ZMQ" not in os.environ and "WEB" not in os.environ:
    print("The car must be off before running joystickd.")
    exit()

  print()
  if args.keyboard:
    print('Gas/brake control: `W` and `S` keys')
    print('Steering control: `A` and `D` keys')
    print('Buttons')
    print('- `R`: Resets axes')
    print('- `C`: Cancel cruise control')
  else:
    print('Using joystick, make sure to run cereal/messaging/bridge on your device if running over the network!')

  joystick = Keyboard() if args.keyboard else Joystick(args.gamepad)
  joystick_thread(joystick)