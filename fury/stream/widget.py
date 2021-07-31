import subprocess
import numpy as np
import sys
if sys.version_info.minor >= 8:
    PY_VERSION_8 = True
else:
    PY_VERSION_8 = False
try:
    from IPython.display import IFrame
    from IPython.core.display import display
    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False

import time
import socket
import errno

from fury.stream.client import FuryStreamClient, FuryStreamInteraction


def check_port_is_available(host, port):
    """Check if a given port it's available

    Parameters
    ----------
    host : str
    port : int

    Returns
    -------
    available : bool

    """
    available = True
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
    except socket.error as e:
        if e.errno == errno.EADDRINUSE:
            available = False
    s.close()
    return available


class Widget:
    def __init__(
            self, showm, ms_stream=0,
            ms_interaction=33,
            host='localhost', port=None,
            encoding='mjpeg', ms_jpeg=33,
            queue_size=20):
        """Thi Obj it's able execute the fury streaming system
        using the SharedMemory from python multiprocessing.

        Parameters
        ----------
        showm : ShowmManager
        ms_stream : float, optional
            time in mileseconds between each frame buffer update.
        ms_interaction : float, optional
            time in mileseconds between each user interaction update.
        host : str, optional
        port : int, optional
        encoding : str, optional
            If should use MJPEG streaming or WebRTC.
        ms_jpeg : float, optional
            This it's used  only if the MJPEG will be used. The
            ms_jpeg represents the amount of miliseconds between to
            consecutive calls of the jpeg enconding.
        queue_size : int, optional
            maximum number of user interactions to be stored

        """
        if not PY_VERSION_8:
            raise ImportError('Python 3.8 or greater is required to use the\
                widget class')
        self.showm = showm
        self.window_size = self.showm.size
        max_window_size = (
            int(self.window_size[0]*(1+0.1)),
            int(self.window_size[1]*(1+0.1))
        )
        self.max_window_size = max_window_size
        self.ms_stream = ms_stream
        self.ms_interaction = ms_interaction
        self.ms_jpeg = ms_jpeg
        self._host = host
        if port is None:
            port = np.random.randint(7000, 8888)
        self._port = port
        self.queue_size = queue_size
        self._server_started = False
        self.pserver = None
        self.encoding = encoding
        self.showm.window.SetOffScreenRendering(1)
        self.showm.iren.EnableRenderOff()

    @property
    def command_string(self):
        """Return the command string to start the server

        Returns
        -------
        command_string : str

        """
        s = 'from fury.stream.server import web_server;'
        s += "web_server(image_buffer_names="
        s += f"{self.stream.img_manager.image_buffer_names}"
        s += f",info_buffer_name='{self.stream.img_manager.info_buffer_name}',"
        s += "queue_head_tail_buffer_name='"
        s += f"{self.stream_interaction.circular_queue.head_tail_buffer_name}'"
        s += ",queue_buffer_name='"
        s += f"{self.stream_interaction.circular_queue.buffer.buffer_name}'"
        if self.encoding == 'mjpeg':
            s += ",provides_mjpeg=True"
            s += f",ms_jpeg={self.ms_jpeg}"
            s += ",provides_webrtc=False"
        s += f",port={self._port},host='{self._host}',"
        s += "avoid_unlink_shared_mem=True"
        s += ")"
        return s

    def _start_fury_client(self):
        """Start the fury image buffer client and the interaction client
        """
        if self._server_started:
            self.stop()

        self.stream = FuryStreamClient(
            self.showm,
            max_window_size=self.max_window_size,
            use_raw_array=False,
            whithout_iren_start=True
        )
        self.stream_interaction = FuryStreamInteraction(
            self.showm, max_queue_size=self.queue_size,
            whithout_iren_start=True,
            use_raw_array=False)

        self.stream_interaction.start(ms=self.ms_interaction)
        self.stream.start(self.ms_stream)
        self._server_started = True
        self.pserver = None

    def run_command(self):
        """Evaluate the command string to start the server
        """
        if self.pserver is not None:
            self._kill_server()

        i = 0
        available = check_port_is_available(self._host, self._port)
        while not available and i < 50:
            self._port = np.random.randint(7000, 8888)
            available = check_port_is_available(self._host, self._port)
            i += 1
        if not available:
            return False

        if self._server_started:
            args = [
                sys.executable, '-c',
                self.command_string
            ]
            self.pserver = subprocess.Popen(
                args,
                # f'python -c "{self.command_string}"',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
        return True

    @property
    def url(self):
        url = f'http://{self._host}:{self._port}'
        url += f'?iframe=1&encoding={self.encoding}'
        return url

    def return_iframe(self, height=200):
        """Return the jupyter div iframe used to show the stream
        """
        if IPYTHON_AVAILABLE:
            display(IFrame(
                self.url,
                '100%', f'{int(height)}px')
            )

    def start(self):
        """Start the fury client and the interaction client and return the url
        """
        self._start_fury_client()
        ok = self.run_command()
        if not ok:
            self.stop()
            return False
        print(f'url: {self.url}')

    def display(self, height=150):
        """Start the server and display the url in an iframe
        """
        self._start_fury_client()
        ok = self.run_command()
        if not ok:
            self.stop()
            return False
        time.sleep(2)
        self.return_iframe(height)

    def stop(self):
        """Stop the streaming server and release the shared memory
        """
        if self._server_started:
            self.stream.stop()
            self.stream_interaction.stop()

            if self.pserver is not None:
                self._kill_server()
            self.cleanup()
        self._server_started = False

    def _kill_server(self):
        """Kill the server process
        """
        self.pserver.kill()
        self.pserver.wait()
        self.pserver = None

    def cleanup(self):
        """Release the shared memory
        """
        if self.stream is not None:
            self.stream.cleanup()

        if self.stream_interaction is not None:
            self.stream_interaction.cleanup()

    def __del__(self):
        self.stop()
