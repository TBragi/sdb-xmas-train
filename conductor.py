import os, random, math, time as timer
from datetime import datetime, timedelta, time
from glob import glob
import RPi.GPIO as GPIO
from mutagen.mp3 import MP3
from omxplayer.player import OMXPlayer
import numpy as np

"""CONSTANTS"""
motor_vr_pin = 12
motor_relay_pin = 13
ssr_pin = 11


""" music variables """
MUSIC_LIB_PATH = '/media/usb'
last_played_track = None
stop_music_time = 0
player = None
playlist = []
run_music = False
new_playlist = True
playlist_duration = 0
track_stop_time = 0
tracks_to_play = 2


""" motor and speed """
motor = None
MAX_SPEED = 50
MIN_SPEED = 10
BOOT_COEF = 4
BREAK_COEF = 2
GRAPH_TRANSITION_THRESHOLD = 5 # between 0 and MAX_SPEED: (MAX_SPEED/2) will eliminate the feature


""" managing variable """
OPEN_HOUR = time(8, 0, 0)
CLOSE_HOUR = time(20, 0, 0)
progress_start_time = 0
default_run_time = 40
run_time = default_run_time
stop_time = (10 * 60)
print_time = 0
progress = 0


def setup():
  """program initialization"""
  print('Choo! Choo! The train is booting..')

  global motor, motor_vr_pin, progress_start_time, MUSIC_LIB_PATH

  # configure motor IO
  GPIO.setmode(GPIO.BOARD)
  GPIO.setwarnings(False)
  GPIO.setup(motor_vr_pin, GPIO.OUT)
  GPIO.setup(ssr_pin, GPIO.OUT)
  GPIO.setup(motor_relay_pin, GPIO.OUT)

  GPIO.output(ssr_pin, GPIO.LOW)
  GPIO.output(motor_relay_pin, GPIO.LOW)

  motor = GPIO.PWM(motor_vr_pin, 1000)
  motor.start(100-0)

  if os.path.exists(os.path.join(MUSIC_LIB_PATH, 'normalized_tracks')):
    MUSIC_LIB_PATH = os.path.join(MUSIC_LIB_PATH, 'normalized_tracks')
    print('Found normalized tracks directory')

  current_date = datetime.now()
  current_time = datetime.timestamp(current_date)
  progress_start_time = current_time
  progress = 0

  print('found upbeat playlist:\n', get_upbeat_playlist(), '\nand playlist:\n', get_playlist(), '\n')
  print('Ready!')


def loop_async():
  """main loop that implements a non-blocking strategy"""
  global motor, progress_start_time, MIN_SPEED, run_time, stop_time, new_playlist, player, playlist, track_stop_time, new_player, tracks_to_play, default_run_time, print_time, progress

  """ time trackers """
  current_date = datetime.now()
  current_time = datetime.timestamp(current_date)
  shop_is_open = is_shop_open(current_date)
  progress = 0
  speed = MIN_SPEED
  progress = current_time - progress_start_time


  if shop_is_open is True:


    """ populate playlist """
    if new_playlist is True: # and not playlist:
      new_playlist = False
      playlist = []
      playlist_duration = default_run_time
      run_time = default_run_time

      # try to populate playlist
      try:
        playlist += [get_upbeat_track()]
      except:
        print('No upbeat tracks available')

      try:
        playlist += get_sub_playlist(tracks_to_play)
      except:
        print('No music tracks available')

      if playlist:
        playlist_duration = sum(track.info.length for track in [MP3(mp3_file) for mp3_file in playlist])
        run_time = playlist_duration

  else:
    progress_start_time = current_time


  """ if playlist has tracks """
  if playlist:
    if current_time > track_stop_time:

      """ create or reuse player instance """
      try:
        player.load(playlist[0])
        print('Reusing player')
      except:
        player = OMXPlayer(playlist[0])
        print('New player')

      """ next stop """
      try:
        track_stop_time = player.duration() + current_time
      except:
        print('Current playing track duration exception')
        track_stop_time = default_run_time + current_time
        run_time = default_run_time

      playlist.pop(0)


  """ compute speed """
  speed = speed_graph(progress, duration=run_time)
  if progress < 2:
    speed = 100

  if not shop_is_open:
    speed = 0

  """ reset and prepare for new run """
  if progress > (run_time+stop_time) and new_playlist is False:
    progress_start_time = current_time
    new_playlist = True

  relay_on = int(speed) > (MIN_SPEED + 0.5) and shop_is_open
  GPIO.output(motor_relay_pin, relay_on)
  GPIO.output(ssr_pin, shop_is_open)
  motor.ChangeDutyCycle(100-int(speed))

  if current_time > print_time:
    print_time = current_time + 1
    print('{}  (shop is {})   |   progress: {:03.0f}, {:03.0f}, {:03.0f} ({:03.0f}%)  speed: {:.02f}  (relay {})   |  stop music at: {:.02f}  playlist: {}'.format(current_date, ("open" if shop_is_open else "closed"), progress, run_time, stop_time, progress/(run_time+stop_time)*100, speed, "on" if relay_on else "off", track_stop_time, [track.split('/')[-1] for track in playlist]), end='\n',flush=False)



def speed_graph(progress, duration):
  """computes a speed graph from the given progress and duration times"""
  global MAX_SPEED, MIN_SPEED, GRAPH_TRANSITION_THRESHOLD, BOOT_COEF, BREAK_COEF

  SPEED = MAX_SPEED - MIN_SPEED

  """ lower bounds (pick largest number) """
  progress = max(0, progress)
  duration = max(30, duration)

  """ shared computations """
  numerator = np.log((SPEED / GRAPH_TRANSITION_THRESHOLD) - 1)

  """ boot graph """
  boot_graph_offset = (numerator / np.log(BOOT_COEF))
  boot_vector = SPEED / (1 + BOOT_COEF**(-progress + boot_graph_offset))

  """ break graph """
  break_graph_offset = (numerator / np.log(BREAK_COEF)) - duration
  break_vector = SPEED / (1 + BREAK_COEF**(progress + break_graph_offset))

  """ compute final speed vector """
  speed_vector = boot_vector + break_vector - SPEED + MIN_SPEED

  """ constrain and return """
  return min(100, max(0, speed_vector))




def is_shop_open(date):
    """return true if x is in the range [OPEN_HOUR, CLOSE_HOUR]"""
    global OPEN_HOUR, CLOSE_HOUR
    if OPEN_HOUR <= CLOSE_HOUR:
        return OPEN_HOUR <= date.time() <= CLOSE_HOUR
    else:
        return OPEN_HOUR <= date.time() or date.time() <= CLOSE_HOUR



def get_sub_playlist(tracks_to_play):
  """returns a playlist fraction"""
  #return random.sample(get_playlist(), k=tracks_to_play)

  sublist = []
  for i in range(tracks_to_play):
    sublist.append(get_new_track())
  return sublist


def get_upbeat_playlist():
  playlist = get_full_playlist()
  upbeat_tracks = [track for track in playlist if 'upbeat' in track]
  return upbeat_tracks


def get_upbeat_track():
  """returns path to a random upbeat track"""
  try:
    upbeat_tracks = get_upbeat_playlist()
    return random.choice(upbeat_tracks)
  except:
    return []


def get_new_track():
  """returns a new track, that was not the previous"""
  global last_played_track

  """ get playliste and pick track """
  playlist = get_playlist()
  track = random.choice(playlist)

  """ exclude last played track, if others are available """
  if len(playlist) > 1 and last_played_track != None:
    while last_played_track == track:
      track = random.choice(playlist)

  last_played_track = track
  return track



def get_playlist():
  """gets the full playlist without the intro track"""
  return np.setdiff1d(get_full_playlist(), get_upbeat_playlist())



def get_full_playlist():
  """gets all tracks from the usb"""
  return glob(os.path.join(MUSIC_LIB_PATH, '*.mp3'))


def normalize_playlist_volume(playlist, volume):
   print('Normalizing {} tracks with {} db'.format(len(playlist), volume))
   for track in  playlist:
      track_name = track.replace(MUSIC_LIB_PATH+'/', '')
      print('Normalizing', track_name)
      try:
        sound = AudioSegment.from_file(track, 'mp3')
        normalized_track = match_target_amplitude(sound, volume)
        normalized_track.export('{}/normalized_{}.mp3'.format(MUSIC_LIB_PATH, track_name), format='mp3')
        print('normaliztion succeeded')
      except:
        print('failed to normalize track',track_name)

   print('Normalizing finished')


def match_target_amplitude(track, target_dBFS):
  change_in_dBFS = target_dBFS - track.dBFS
  return track.apply_gain(change_in_dBFS)


def main():
  global player, motor

  try:
    setup()
    while True:
      loop_async()
  except KeyboardInterrupt:
    pass

  try:
    motor.stop()
    GPIO.cleanup()
  except:
    print('IO termination exception')

  try:
    player.stop()
  except:
    print('Player termination exception')


if __name__ == '__main__':
  main()


"""
      try:
        #playlist = [get_upbeat_track()] + get_sub_playlist(tracks_to_play)
        playlist_duration = sum(track.info.length for track in [MP3(mp3_file) for mp3_file in playlist])
        run_time = playlist_duration
        print('playlist', playlist, 'has length', playlist_duration)
      except:
        print('Could not get playlist!')
"""
