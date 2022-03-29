import os
import asyncio
import json
import socket
import webbrowser
import spotipy
import pyperclip
import websockets
from itertools import count, cycle
import PySimpleGUI as GUI # noqa
from spotipy.oauth2 import SpotifyOAuth

directory_path = os.path.expandvars("C:/Users/%username%/PolyPop/UIX/Sources/Spotify/{}").format
spotify_cache_dir = './.cache'

GUI.theme('Dark')
GUI.SetOptions(font='helvetica 16', scrollbar_color='gray')

connected = False
scope = "user-read-playback-state,user-library-read,user-modify-playback-state,user-read-currently-playing"
sp: spotipy.Spotify
client = None
devices = []
current_track = None
current_shuffle = None
current_repeat = None
current_volume = None
current_state = None
tasks = []
credentials = {'client_id': None, 'client_secret': None}
repeat_states = {'Song': 'track', 'Enabled': 'context', 'Disabled': 'off'}
app: asyncio.Future
round_volume_to = 5


def get_open_port():
    sock = socket.socket()
    sock.bind(('', 0))
    return sock.getsockname()[1]


p = os.environ['SPOTIFY_PORT'] = str(get_open_port())
print(p)
del p


def volume_format(v):
    return float('%.2f' % v)


def create_layout():
    return [[
        GUI.Column([
            [GUI.Text('Welcome to the PolyPop Spotify Plugin!',
                      font='helvetica 20 bold')],
            [GUI.Text('Created by Jab!', font='helvetica 20 bold')],
            [GUI.Image(directory_path('poly to sp.png'))],
            [GUI.Text('Please follow the steps below to setup the Spotify Plugin:',
                      font='helvetica 18 bold underline')],
            [GUI.Text('', font='helvetica 20 bold')],
            [GUI.Text('1: Goto https://developer.spotify.com/dashboard/login and login')],
            [GUI.Text('(click the image below to redirect to the Developer Site)',
                      font='helvetica 12 bold underline')],
            [GUI.Button('Login',
                        image_filename=directory_path('Log In.png'),
                        font="helvetica 2")],
            [GUI.Text('2: Click Create App')],
            [GUI.Image(directory_path('Create App.png'))],
            [GUI.Text('3: Fill In the App Name, Description, and Check the "I Agree" box. Then Click "Create"')],
            [GUI.Image(directory_path('App Info.png'))],
            [GUI.Text('4: Click on "Edit Settings"')],
            [GUI.Image(directory_path('Edit Settings.png'))],
            [GUI.Text('5: Paste "http://localhost:38042" into the "Redirect URIs and click Add')],
            [GUI.Text('(click the image below to copy the URL to your clipboard)',
                      font='helvetica 12 bold underline')],
            [GUI.Button("Redirect",
                        image_filename=directory_path('Redirect URI.png'),
                        font='helvetica 2')],
            [GUI.Text('6: Click save at the bottom of that screen')],
            [GUI.Text('7: Copy the Client ID and Client Secret to the below Fields and Click Done!')],
            [GUI.Image(directory_path('Client Info.png'))],
            [GUI.Text('(reveal the client secret by clicking the green text)',
                      font='helvetica 12 italic')],
            [GUI.Text('', font='helvetica 30 italic')],
            [GUI.Text('Client ID', font='helvetica 18 bold')],
            [GUI.InputText()],
            [GUI.Text('Client Secret', font='helvetica 18 bold')],
            [GUI.InputText()],
            [GUI.Button('Ok'), GUI.Button('Cancel')],
            [GUI.Text('', font='helvetica 40 italic')]],
            scrollable=True, element_justification='center', vertical_scroll_only=True, expand_x=True)
        ]
    ]


async def request_spotify_setup():
    if os.path.exists(spotify_cache_dir):
        os.remove(spotify_cache_dir)
    window_name = 'Spotify Setup'

    while True:
        window = GUI.Window(window_name, create_layout(), resizable=True,
                            force_toplevel=True, icon='./icon.ico', finalize=True)
        while True:
            event, values = window.read()

            if event == GUI.WIN_CLOSED or event == 'Cancel':  # if user closes window or clicks cancel
                return
            if event == "Login":
                webbrowser.open_new('https://developer.spotify.com/dashboard/login')
                continue
            if event == "Redirect":
                pyperclip.copy(f"http://localhost")
                continue
            break

        window.close()
        client_id, client_secret = map(str.strip, values.values())

        missing = "Client ID " if not client_id else ""
        if not client_secret:
            missing += ("and " if client_id else "") + "Client Secret"

        if not missing:
            await connect_to_spotify(client_id, client_secret, True)
            return True
        GUI.popup_ok(f"Missing {missing}", title=f"Missing {missing}")


def get_all_playlists():
    playlists = []
    for i in count():
        pl = sp.current_user_playlists(offset=i)
        playlists.extend(pl.get('items'))
        if not pl.get('next'):
            break

    if not playlists:
        return {0: 'No Playlists'}
    return {p.get('name'): p.get('uri') for p in playlists}


async def connect_to_spotify(client_id, client_secret, setup=False):
    global sp
    global client
    global current_shuffle
    global current_repeat
    global current_volume
    global current_state
    global credentials
    if credentials.get('client_id') != client_id and credentials.get('client_secret') != client_secret:
        if setup:
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri="http://localhost:38042",
                scope=scope)
        else:
            auth_manager = spotipy.SpotifyPKCE(
                client_id=client_id,
                # client_secret=client_secret,
                redirect_uri="http://localhost:38042",
                scope=scope)

        try:
            sp = spotipy.Spotify(auth_manager=auth_manager)
        except spotipy.oauth2.SpotifyOauthError:
            return

    me = sp.me()
    current_playback = sp.current_playback() or {}
    curr_device = current_playback.get('device', {})
    now_playing_info = sp.currently_playing()
    current_shuffle = current_playback.get('shuffle_state')
    current_repeat = current_playback.get('repeat_state')
    current_volume = volume_format(curr_device.get('volume_percent', 0) / 1)
    await client.send(json.dumps({
        'action': "spotify_connect",
        'data': {
            'name': me["display_name"],
            'user_image_url': me.get('images')[0].get('url'),
            'devices': [d.get('name') for d in get_devices()],
            'current_device': curr_device.get('name'),
            'client_id': client_id,
            'client_secret': client_secret,
            'is_playing': bool(now_playing_info),
            'playlists': get_all_playlists(),
            'shuffle_state': current_shuffle,
            'repeat_state': current_repeat,
            'volume': current_volume
        }
    }))
    global connected
    connected = True

    tasks.append(asyncio.create_task(exec_every_x_seconds(0.5, check_now_playing)))
    tasks.append(asyncio.create_task(exec_every_x_seconds(1, check_sp_settings)))
    # tasks.append(asyncio.create_task(exec_every_x_seconds(5, check_volume)))


def clear_tasks():
    global tasks
    for task in tasks:
        task.cancel()
    tasks = []


def get_devices():
    return sp.devices().get('devices')


async def play(data):
    device_id = next(d.get('id') for d in get_devices() if d.get('name') == data.get('device_name'))
    playlist_uri = data.get('playlist_uri')
    try:
        if playlist_uri:
            sp.start_playback(device_id=device_id, context_uri=playlist_uri)
            return
        sp.start_playback(device_id=device_id)
        return
    except spotipy.SpotifyException:
        await client.send(json.dumps({'action': 'error', 'data': {'command': 'play'}}))


def pause():
    try:
        sp.pause_playback()
    except spotipy.SpotifyException:
        pass


def next_track():
    sp.next_track()


def previous_track():
    try:
        sp.previous_track()
    except spotipy.SpotifyException:
        pass


def shuffle(data):
    sp.shuffle(data.get('state', False))


def repeat(data):
    sp.repeat(repeat_states[data.get('state', 'Disabled')])


def volume(data):
    sp.volume(data)


async def exec_every_x_seconds(timeout, func):
    while True:
        await asyncio.sleep(timeout)
        await func()


async def check_sp_settings():
    global sp
    global client
    global current_shuffle
    global current_repeat
    global current_volume
    info = sp.current_playback()
    ret = {}
    new_shuffle = info.get('shuffle_state')
    new_repeat = info.get('repeat_state')
    device_info = info.get('device', {})
    # new_volume = volume_format(device_info.get('volume_percent', 1))

    if current_shuffle != new_shuffle:
        ret['shuffle_state'] = new_shuffle
        current_shuffle = new_shuffle
    if current_repeat != new_repeat:
        ret['repeat_state'] = new_repeat
        current_repeat = new_repeat

    if ret:
        await client.send(f'{{"action": "update", "data": {json.dumps(ret)}}}')


async def check_volume():
    global sp
    global client
    global current_volume
    info = sp.current_playback()
    
    new_volume = volume_format(info.get('device', {}).get('volume_percent', 1))
    if current_volume != new_volume:
        await client.send(f'{{"action": "update", "data": {{"volume": {new_volume}}}}}')
        current_volume = new_volume


async def check_now_playing():
    global client
    global current_track
    track = sp.currently_playing()
    track_name = track.get('item', {}).get('id')

    if current_track == track_name:
        return

    current_track = track_name

    if not track:
        await client.send(json.dumps({'action': 'playing_ended'}))
        return

    await client.send(json.dumps({
        'action': 'song_changed',
        'data': track}))


def update_settings(data):
    global current_shuffle
    global current_repeat
    global current_volume
    new_shuffle = data.get('shuffle_state')
    new_repeat = data.get('repeat_state')
    new_volume = data.get('volume')
    if new_shuffle is not None:
        shuffle({'state': new_shuffle})
        current_shuffle = new_shuffle
    if new_repeat:
        repeat({'state': new_repeat})
        current_repeat = new_repeat
    if new_volume:
        volume(int(new_volume * 100))
        current_volume = new_volume


track_funcs_no_data = {
    'pause': pause,
    'next': next_track,
    'previous': previous_track,
    'get_devices': get_devices}

track_funcs_with_data = {
    'shuffle_state': shuffle,
    'repeat_state': repeat,
    'update': update_settings,
    'volume': volume}


async def on_connected(websocket, data):
    global tasks
    global client
    client = websocket
    client_id, client_secret = data.values()
    if client_id and client_secret:
        await connect_to_spotify(client_id, client_secret)


async def on_message(websocket):
    while True:
        async for message in websocket:
            payload = json.loads(message)
            action = payload.get('action')

            if not action:
                continue
            func = track_funcs_no_data.get(action)
            if func:
                func()  # noqa

            data = payload.get('data')
            func = track_funcs_with_data.get(action)
            if func:
                func(data)

            if action == 'connected_handshake':
                await on_connected(websocket, data)
            if action == 'login':
                await request_spotify_setup()
            if action == 'play':
                await play(data)
            if action == 'quit':
                app.done()


async def main():
    global app
    app = asyncio.Future()
    async with websockets.serve(on_message, "localhost", 38041):
        await app


if __name__ == "__main__":
    asyncio.run(main())
