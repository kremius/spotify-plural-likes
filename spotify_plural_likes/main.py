"""
Prerequisites
    pip3 install spotipy Flask Flask-Session
    // from your [app settings](https://developer.spotify.com/dashboard/applications)
    export SPOTIPY_CLIENT_ID=client_id_here
    export SPOTIPY_CLIENT_SECRET=client_secret_here
    export SPOTIPY_REDIRECT_URI='http://127.0.0.1:8080' // must contain a port
    // SPOTIPY_REDIRECT_URI must be added to your [app settings](https://developer.spotify.com/dashboard/applications)
    OPTIONAL
    // in development environment for debug output
    export FLASK_ENV=development
    // so that you can invoke the app outside of the file's directory include
    export FLASK_APP=/path/to/spotipy/examples/app.py

    // on Windows, use `SET` instead of `export`
Run app.py
    python3 -m flask run --port=8080
    NOTE: If receiving "port already in use" error, try other ports: 5000, 8090, 8888, etc...
        (will need to be updated in your Spotify app and SPOTIPY_REDIRECT_URI variable)
"""

import os
from flask import Flask, session, request, redirect
from flask_session import Session
import spotipy
import uuid
import atexit

from apscheduler.schedulers.background import BackgroundScheduler
from os import listdir

import logging
from gevent.pywsgi import WSGIServer

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(64)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '../flask_session/'
Session(app)

caches_folder = '../spotify_caches/'
if not os.path.exists(caches_folder):
    os.makedirs(caches_folder)


def session_cache_path():
    return caches_folder + session.get('uuid')


@app.route('/')
def index():
    if not session.get('uuid'):
        # Step 1. Visitor is unknown, give random ID
        session['uuid'] = str(uuid.uuid4())

    auth_manager = spotipy.oauth2.SpotifyOAuth(scope='playlist-modify-public',
                                               cache_path=session_cache_path(),
                                               show_dialog=True)

    if request.args.get("code"):
        # Step 3. Being redirected from Spotify auth page
        auth_manager.get_access_token(request.args.get("code"))
        return redirect('/')

    if not auth_manager.get_cached_token():
        # Step 2. Display sign in link when no token
        auth_url = auth_manager.get_authorize_url()
        return f'<h2><a href="{auth_url}">Sign in</a></h2>'

    # Step 4. Signed in, display data
    spotify = spotipy.Spotify(auth_manager=auth_manager)
    return f'<h2>Hi {spotify.me()["display_name"]}, ' \
           f'<small><a href="/sign_out">[sign out]<a/></small></h2>' \
           f'<a href="/playlists">my playlists</a> | ' \
           f'<a href="/create_playlist">create</a> | '


@app.route('/sign_out')
def sign_out():
    session.clear()
    try:
        # Remove the CACHE file (.cache-test) so that a new user can authorize.
        os.remove(session_cache_path())
    except OSError as e:
        app.logger.error("Error: %s - %s." % (e.filename, e.strerror))
    return redirect('/')


@app.route('/create_playlist')
def create_playlist():
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_path=session_cache_path())
    if not auth_manager.get_cached_token():
        return redirect('/')

    spotify = spotipy.Spotify(auth_manager=auth_manager)
    me = spotify.me()
    return spotify.user_playlist_create(me['id'], 'Test Robo Playlist', public=True, description='')


def fetch_playlist_tracks(spotify, playlist_id):
    app.logger.info(f"Fetching songs from playlist {playlist_id}")
    tracks = []
    offset = 0
    while True:
        tracks_data = spotify.playlist_tracks(
            playlist_id, fields='items.track.id,items.track.name,next', offset=offset)
        tracks_chunk = tracks_data['items']
        tracks.extend(tracks_chunk)
        offset += len(tracks_chunk)
        if not tracks_data['next']:
            break
    return tracks


def update_likes_for_user(user_uuid):
    print(f'Updating likes for {user_uuid}')

    path = caches_folder + user_uuid
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_path=path)
    if not auth_manager.get_cached_token():
        return

    spotify = spotipy.Spotify(auth_manager=auth_manager)

    # TODO: maximum limit is 50, so offset is needed
    playlists_data = spotify.current_user_playlists()
    if not playlists_data:
        app.logger.error('No playlists data!')
        return

    next_data = playlists_data['next']
    if next_data:
        app.logger.error("Too many playlists: it's needed to implement offset fetch")
        return

    playlists = playlists_data['items']
    for playlist in playlists:
        playlist_id = playlist['id']
        app.logger.info(f"id: {playlist_id}, name: {playlist['name']}, type: {playlist['type']}")
        tracks = fetch_playlist_tracks(spotify, playlist_id)
        app.logger.info(f'{len(tracks)}, {tracks}')


def update_likes():
    print('Updating likes')
    for user_uuid in listdir(caches_folder):
        update_likes_for_user(user_uuid)


def main():
    basic_config = {
        'level': logging.INFO,
        'format': '[%(levelname)s] [%(name)s] %(asctime)s: %(message)s'
    }
    logging.basicConfig(**basic_config)

    app.logger.info('=-------------------spotify-plural-likes started-------------------=')

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=update_likes, trigger="interval", seconds=10)
    scheduler.start()

    atexit.register(lambda: scheduler.shutdown())

    http_server = WSGIServer(('0.0.0.0', int(os.environ.get("PORT", 8080))), app, log=app.logger, error_log=app.logger)
    http_server.serve_forever()
