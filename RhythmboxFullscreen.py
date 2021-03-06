# -*- Mode: python; coding: utf-8; tab-width: 4; indent-tabs-mode: nil; -*-
#
# Copyright (C) 2013 - Benjamin Bach <benjamin@overtag.dk>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.

import mimetypes

from gi.repository import GObject #@UnresolvedImport
from gi.repository import Gtk #@UnresolvedImport
from gi.repository import Peas #@UnresolvedImport
from gi.repository import RB #@UnresolvedImport
from gi.repository import GdkPixbuf #@UnresolvedImport

from os import path, listdir
from urllib import url2pathname

import FullscreenWindow

from RhythmboxFullscreenPrefs import Preferences #@UnusedImport

from fullscreen_rb3compat import ActionGroup
from fullscreen_rb3compat import Action
from fullscreen_rb3compat import ApplicationShell

ui_str = \
"""<ui>
  <menubar name="MenuBar">
    <menu name="ViewMenu" action="View">
      <placeholder name="ViewMenuModePlaceholder">
        <menuitem name="ViewMenuToggleFullscreen" action="ToggleFullscreen"/>
      </placeholder>
    </menu>
  </menubar>
</ui>"""

# Scales the prefetched album art for later use
ALBUM_ART_W = 800
ALBUM_ART_H = 800

def find_plugin_file(filename):
    """Since there were a couple of unresolved issues with rb.find_plugin_file,
    we use our own little utility function"""
    root_dir = path.abspath(path.split(__file__)[0])
    path_to_file= path.join(root_dir, filename)
    if path.exists(path_to_file):
        return path_to_file
    return None

class FullscreenTrack():
    
    def __init__(self, artist=None, title=None, album=None, duration=0.0, entry=None):
        self.artist = artist
        self.title = title
        self.album = album
        self.duration = duration
        self.entry = entry
    
    def __eq__(self, obj):
        # Do not compare RB entry object because it changes
        return (
            self.artist == obj.artist and
            self.title == obj.title and
            self.album == obj.album and
            self.duration == obj.duration
        )

class FullscreenView (GObject.Object, Peas.Activatable):
    __gtype_name = 'FullscreenPlugin'
    object = GObject.property(type=GObject.Object) #@ReservedAssignment
    
    def __init__(self):
        super(FullscreenView, self).__init__()
                
    def do_activate(self):
        shell = self.object
        data = {}
        self.shell = shell
        self.entries = None

        self.action_group = ActionGroup(self.shell, 'FullscreenPluginActions')
        action = self.action_group.add_action(func=self.show_fullscreen,
            action_name='ToggleFullscreen', label='Full Screen',
            action_type='app', accel="F12")

        self._appshell = ApplicationShell(self.shell)
        self._appshell.insert_action_group(self.action_group)
        self._appshell.add_app_menuitems(ui_str, 'FullscreenPluginActions', 'view')
        
    def do_deactivate(self):
        shell = self.object
        self._appshell.cleanup()

    def show_fullscreen(self, *args):
        self.window = FullscreenWindow.FullscreenWindow(plugin=self)
        
        # Receive notification of song changes
        self.player = self.shell.props.shell_player
        self.player.connect("playing-source-changed", self.reload_playlist)
        self.player.connect("playing-song-changed", self.on_playing_song_changed)
        self.player.connect("playing-changed", self.reload_play_pause)
        
        # TODO: This signal is not fired - which should we listen for?
        # We should use the cover_db,
        # but what are its signals??
        cover_db = RB.ExtDB(name='album-art')
        self.player.connect("playing-song-property-changed", self.notify_metadata)
        cover_db.connect("added", self.notify_cover_art_change)

        # Load current state
        self.reload_playlist(self.player, self.player.get_playing_entry())

    def playpause(self):
        # Argument 'True' is unused
        #(see http://developer.gnome.org/rhythmbox/2.98/RBShellPlayer.html#rb-shell-player-playpause)
        self.player.playpause(True)
        
    def play_entry(self, index):
        if len(self.tracks) > index:
            self.player.play_entry(self.tracks[index].entry,
                self.shell.get_property("library-source"))

    def reload_play_pause(self, player, playing):
        if not self.window.track_widgets:
            return
        if playing:
            try:
                elapsed = player.get_playing_time()
            except:
                elapsed = (True, 0.0)
            self.window.track_widgets[self.window.current_track].paused=False
            self.window.track_widgets[self.window.current_track].start_progress_bar(elapsed)
            self.window.current_info = "Now playing..."
            self.window.track_infos[0] = FullscreenWindow.FullscreenWindow.INFO_STATUS_PAUSE
        else:
            self.window.track_widgets[self.window.current_track].paused=True
            self.window.current_info = FullscreenWindow.FullscreenWindow.INFO_STATUS_IDLE
            self.window.track_infos[0] = FullscreenWindow.FullscreenWindow.INFO_STATUS_PLAY

    def get_entries(self, player, entry, cnt):
        """Gets the next and previous entries to be played from both active source and queue
        
        Next entries: Everything from source and queue
        Previous entries: Everything just from the source
        
        Uses each source's query-model.
        player = player to use
        entry = entry to start from (as a kind of offset)
        cnt = number of entries to return
        """

        if not entry:
            return []
        
        entries = [entry]
        
        def get_entries(property_name, backwards):
            queue = player.get_property(property_name)
            if queue:
                querymodel = queue.get_property("query-model")
                if not backwards:
                    l = querymodel.get_next_from_entry(entry)
                    while l and len(entries) <= cnt:
                        entries.append(l)
                        l = querymodel.get_next_from_entry(l)
                else:
                    l = querymodel.get_previous_from_entry(entry)
                    while l and len(entries) <= cnt:
                        entries.insert(0, l)
                        l = querymodel.get_previous_from_entry(l)
        
        
        get_entries("queue-source", False)
        get_entries("source", True)
        get_entries("source", False)

        return entries

    def get_track_info(self, entry):
        artist = entry.get_string(RB.RhythmDBPropType.ARTIST)#.replace('&', '&amp;')
        album = entry.get_string(RB.RhythmDBPropType.ALBUM)#.replace('&', '&amp;')
        title = entry.get_string(RB.RhythmDBPropType.TITLE)#.replace('&', '&amp;')
        duration = entry.get_ulong(RB.RhythmDBPropType.DURATION)
        track = FullscreenTrack(
            artist=artist,
            album = album,
            title = title,
            duration = duration,
            entry = entry
        )
        return track
    
    def notify_metadata(self, player, uri, prop, *args, **kwargs):
        """Subscribe to metadata changes from database"""
        self.set_cover_art(player.get_playing_entry())
    
    def notify_cover_art_change(self, *args):
        self.set_cover_art(self.shell.props.shell_player.get_playing_entry())
    
    def set_cover_art(self, entry):
        if entry:
            self.window.set_artwork(self.get_cover(entry))

    def get_cover(self, entry):
        if entry:
            
            # Try to find an album cover in the folder of the currently playing track
            cover_dir = path.dirname(url2pathname(entry.get_playback_uri()).replace('file://', ''))
            # TODO: use os.walk()
            if path.isdir(cover_dir):
                for f in listdir(cover_dir):
                    file_name = path.join(cover_dir, f)
                    mt = mimetypes.guess_type(file_name)[0]
                    if mt and mt.startswith('image/'):
                        if True in map(lambda x: x in path.splitext(f)[0].lower(),
                            ['cover', 'album', 'albumart', 'folder', 'front']):
                            return GdkPixbuf.Pixbuf.new_from_file_at_size (file_name, ALBUM_ART_W, ALBUM_ART_H)

            # Otherwise use what's found by the album art plugin
            key = entry.create_ext_db_key(RB.RhythmDBPropType.ALBUM)
            cover_db = RB.ExtDB(name='album-art')
            art_location = cover_db.lookup(key)
            
            if art_location and path.exists(art_location):
                return GdkPixbuf.Pixbuf.new_from_file_at_size (art_location, ALBUM_ART_W, ALBUM_ART_H)
    
    def reload_playlist(self, player, entry):

        entry = player.get_playing_entry()
        if not entry:
            # When there is no entry set for reload playlist, then what's happening?
            # Is everything fine and totally inactive?
            return
        
        # Set cover art
        self.set_cover_art(entry)
        
        self.entries = self.get_entries(player, entry, 100)
        self.tracks = []
        
        for e in self.entries:
            self.tracks.append(self.get_track_info(e))
        
        current_track_index = self.entries.index(entry)
        
        self.window.set_tracks(self.tracks, current_track=current_track_index)
        self.set_active_track_properties(player, entry, current_track_index)

    def set_active_track_properties(self, player, entry, current_track_index):

        try:
            elapsed = player.get_playing_time()
        except:
            elapsed = (True, 0.0)
        
        if player.get_playing():
            self.window.track_widgets[current_track_index].start_progress_bar(elapsed)
            self.window.current_info = "Now playing..." # TODO
        else:
            self.window.track_widgets[current_track_index].set_elapsed(elapsed)
            self.window.current_info = FullscreenWindow.FullscreenWindow.INFO_STATUS_IDLE
        
        self.window.show_info()
    
    def on_playing_song_changed(self, player, entry):
        
        if not self.entries:
            return self.reload_playlist(player, entry)
        
        entry = player.get_playing_entry()
        if not entry:
            # When there is no entry set for reload playlist, then what's happening?
            # Is everything fine and totally inactive?
            return
        
        try:
            current_track_index = self.tracks.index(self.get_track_info(entry))
        except ValueError:
            return self.reload_playlist(player, entry)
        
        self.window.change_playing_track(current_track_index)

        self.set_active_track_properties(player, entry, current_track_index)
    
