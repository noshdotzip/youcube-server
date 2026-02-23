#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Download Functionality of YC
"""

# Built-in modules
from asyncio import run_coroutine_threadsafe
from os import getenv, listdir
from os.path import abspath, dirname, join
import re
from tempfile import TemporaryDirectory

# Local modules
from yc_colours import RESET, Foreground
from yc_logging import NO_COLOR, YTDLPLogger, logger
from yc_magic import run_with_live_output
from yc_spotify import SpotifyURLProcessor
from yc_utils import (
    cap_width_and_height,
    create_data_folder_if_not_present,
    get_audio_name,
    get_video_name,
    is_audio_already_downloaded,
    is_video_already_downloaded,
    remove_ansi_escape_codes,
    remove_whitespace,
)

# optional pip modules
try:
    from orjson import dumps
except ModuleNotFoundError:
    from json import dumps

# pip modules
from sanic import Websocket
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# pylint settings
# pylint: disable=pointless-string-statement
# pylint: disable=fixme
# pylint: disable=too-many-locals
# pylint: disable=too-many-arguments
# pylint: disable=too-many-branches

DATA_FOLDER = join(dirname(abspath(__file__)), "data")
FFMPEG_PATH = getenv("FFMPEG_PATH", "ffmpeg")
SANJUUNI_PATH = getenv("SANJUUNI_PATH", "sanjuuni")
DISABLE_OPENCL = bool(getenv("DISABLE_OPENCL"))
YTDLP_COOKIES = getenv("YTDLP_COOKIES")
YTDLP_PROXY = getenv("YTDLP_PROXY")


def get_format_selectors(is_video: bool) -> tuple[str, str]:
    """
    Return (primary, fallback) format selectors.
    Primary prefers MP4/M4A when available. Fallback allows any container.
    """
    if is_video:
        # Prefer non-HLS MP4 where possible, fallback to any protocol/container.
        primary = (
            "worstvideo[ext=mp4][protocol!=m3u8]+worstaudio[ext=m4a][protocol!=m3u8]/"
            "worst[ext=mp4][protocol!=m3u8]/worst[protocol!=m3u8]"
        )
        fallback = "worstvideo*+worstaudio*/worst"
        return primary, fallback
    # Audio: prefer non-HLS M4A, fallback to any protocol/container.
    primary = "worstaudio[ext=m4a][protocol!=m3u8]/worstaudio[protocol!=m3u8]"
    fallback = "worstaudio*/worst"
    return primary, fallback


HLS_RETRY_ERRORS = (
    "fragment not found",
    "downloaded file is empty",
    "http error 403",
    "forbidden",
)


def is_hls_error(exc: Exception) -> bool:
    return any(token in str(exc).lower() for token in HLS_RETRY_ERRORS)


def select_source_file(temp_dir: str, media_id: str, prefer_video: bool) -> str | None:
    """
    Pick a deterministic source file from a yt-dlp download directory.
    Prefer merged files (id.ext) over fragment-specific files (id.f123.ext).
    """
    files = [f for f in listdir(temp_dir) if not f.endswith(".part")]
    if not files:
        return None

    merged_pattern = re.compile(rf"^{re.escape(media_id)}\.[^.]+$")
    merged = [f for f in files if merged_pattern.match(f)]
    if merged:
        return join(temp_dir, merged[0])

    video_exts = {"mp4", "mkv", "webm", "mov", "avi"}
    audio_exts = {"m4a", "mp3", "aac", "ogg", "opus", "wav", "webm"}
    exts = video_exts if prefer_video else audio_exts

    for f in files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
        if ext in exts:
            return join(temp_dir, f)

    return join(temp_dir, files[0])


def download_video(
    source_file: str,
    media_id: str,
    resp: Websocket,
    loop,
    width: int,
    height: int,
):
    """
    Converts the downloaded video to 32vid
    """
    run_coroutine_threadsafe(
        resp.send(
            dumps({"action": "status", "message": "Converting video to 32vid ..."})
        ),
        loop,
    )

    if NO_COLOR:
        prefix = "[Sanjuuni]"
    else:
        prefix = f"{Foreground.BRIGHT_YELLOW}[Sanjuuni]{RESET} "

    def handler(line):
        logger.debug("%s%s", prefix, line)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "status", "message": line})), loop
        )

    returncode = run_with_live_output(
        [
            SANJUUNI_PATH,
            "--width=" + str(width),
            "--height=" + str(height),
            "-i",
            source_file,
            "--raw",
            "-o",
            join(DATA_FOLDER, get_video_name(media_id, width, height)),
            "--disable-opencl" if DISABLE_OPENCL else "",
        ],
        handler,
    )

    if returncode != 0:
        logger.warning("Sanjuuni exited with %s", returncode)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "error", "message": "Faild to convert video!"})),
            loop,
        )


def download_audio(source_file: str, media_id: str, resp: Websocket, loop):
    """
    Converts the downloaded audio to dfpwm
    """
    run_coroutine_threadsafe(
        resp.send(
            dumps({"action": "status", "message": "Converting audio to dfpwm ..."})
        ),
        loop,
    )

    if NO_COLOR:
        prefix = "[FFmpeg]"
    else:
        prefix = f"{Foreground.BRIGHT_GREEN}[FFmpeg]{RESET} "

    def handler(line):
        logger.debug("%s%s", prefix, line)
        # TODO: send message to resp

    returncode = run_with_live_output(
        [
            FFMPEG_PATH,
            "-i",
            source_file,
            "-f",
            "dfpwm",
            "-ar",
            "48000",
            "-ac",
            "1",
            join(DATA_FOLDER, get_audio_name(media_id)),
        ],
        handler,
    )

    if returncode != 0:
        logger.warning("FFmpeg exited with %s", returncode)
        run_coroutine_threadsafe(
            resp.send(dumps({"action": "error", "message": "Faild to convert audio!"})),
            loop,
        )


def downsample_video(
    source_file: str, media_id: str, resp: Websocket, loop, fps: int
) -> str:
    """
    Downsample the video to a target FPS before running sanjuuni.
    Returns the path to the downsampled file, or the original on failure.
    """
    if fps <= 0:
        return source_file

    run_coroutine_threadsafe(
        resp.send(
            dumps(
                {
                    "action": "status",
                    "message": f"Downsampling video to {fps} fps ...",
                }
            )
        ),
        loop,
    )

    out_file = join(dirname(source_file), f"{media_id}.fps{fps}.mp4")

    if NO_COLOR:
        prefix = "[FFmpeg]"
    else:
        prefix = f"{Foreground.BRIGHT_GREEN}[FFmpeg]{RESET} "

    def handler(line):
        logger.debug("%s%s", prefix, line)

    returncode = run_with_live_output(
        [
            FFMPEG_PATH,
            "-y",
            "-i",
            source_file,
            "-vf",
            f"fps={fps}",
            "-an",
            "-sn",
            "-dn",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "32",
            out_file,
        ],
        handler,
    )

    if returncode != 0:
        logger.warning("FFmpeg downsample exited with %s", returncode)
        return source_file

    return out_file


def download(
    url: str,
    resp: Websocket,
    loop,
    width: int,
    height: int,
    fps: int | None,
    spotify_url_processor: SpotifyURLProcessor,
) -> (dict[str, any], list):
    """
    Downloads and converts the media from the give URL
    """

    is_video = width is not None and height is not None
    target_fps = None
    if fps is not None:
        try:
            target_fps = int(fps)
        except (TypeError, ValueError):
            target_fps = None

    # cap height and width
    if width and height:
        width, height = cap_width_and_height(width, height)

    def my_hook(info):
        """https://github.com/yt-dlp/yt-dlp#adding-logger-and-progress-hook"""
        if info.get("status") == "downloading":
            run_coroutine_threadsafe(
                resp.send(
                    dumps(
                        {
                            "action": "status",
                            "message": remove_ansi_escape_codes(
                                f"download {remove_whitespace(info.get('_percent_str'))} "
                                f"ETA {info.get('_eta_str')}"
                            ),
                        }
                    )
                ),
                loop,
            )

    # FIXME: Cleanup on Exception
    with TemporaryDirectory(prefix="youcube-") as temp_dir:
        primary_format, fallback_format = get_format_selectors(is_video)
        yt_dl_options = {
            "format": primary_format,
            "outtmpl": join(temp_dir, "%(id)s.%(ext)s"),
            "default_search": "auto",
            "restrictfilenames": True,
            "extract_flat": "in_playlist",
            "progress_hooks": [my_hook],
            "logger": YTDLPLogger(),
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "merge_output_format": "mp4",
            "retries": 3,
            "fragment_retries": 5,
            "skip_unavailable_fragments": True,
            "concurrent_fragment_downloads": 1,
        }
        if YTDLP_COOKIES:
            yt_dl_options["cookiefile"] = YTDLP_COOKIES
        if YTDLP_PROXY:
            yt_dl_options["proxy"] = YTDLP_PROXY

        yt_dl = YoutubeDL(yt_dl_options)

        run_coroutine_threadsafe(
            resp.send(
                dumps(
                    {"action": "status", "message": "Getting resource information ..."}
                )
            ),
            loop,
        )

        playlist_videos = []

        if spotify_url_processor:
            # Spotify FIXME: The first media key is sometimes duplicated
            processed_url = spotify_url_processor.auto(url)
            if processed_url:
                if isinstance(processed_url, list):
                    url = spotify_url_processor.auto(processed_url[0])
                    processed_url.pop(0)
                    playlist_videos = processed_url
                else:
                    url = processed_url

        data = yt_dl.extract_info(url, download=False)

        if data.get("extractor") == "generic":
            data["id"] = "g" + data.get("webpage_url_domain") + data.get("id")

        """
        If the data is a playlist, we need to get the first video and return it,
        also, we need to grep all video in the playlist to provide support.
        """
        if data.get("_type") == "playlist":
            for video in data.get("entries"):
                playlist_videos.append(video.get("id"))

            playlist_videos.pop(0)

            data = data["entries"][0]

        """
        If the video is extract from a playlist,
        the video is extracted flat,
        so we need to get missing information by running the extractor again.
        """
        if data.get("extractor") == "youtube" and (
            data.get("view_count") is None or data.get("like_count") is None
        ):
            data = yt_dl.extract_info(data.get("id"), download=False)

        media_id = data.get("id")

        if data.get("is_live"):
            return {"action": "error", "message": "Livestreams are not supported"}

        create_data_folder_if_not_present()

        audio_downloaded = is_audio_already_downloaded(media_id)
        video_downloaded = is_video_already_downloaded(media_id, width, height)

        if not audio_downloaded or (not video_downloaded and is_video):
            run_coroutine_threadsafe(
                resp.send(
                    dumps({"action": "status", "message": "Downloading resource ..."})
                ),
                loop,
            )

            def send_download_error(message: str):
                run_coroutine_threadsafe(
                    resp.send(dumps({"action": "error", "message": message})), loop
                )

            try:
                yt_dl.process_ie_result(data, download=True)
            except DownloadError as exc:
                logger.warning(
                    "Primary download failed (%s). Retrying with fallback format.",
                    exc,
                )
                try:
                    yt_dl_fallback = YoutubeDL(
                        {**yt_dl_options, "format": fallback_format}
                    )
                    yt_dl_fallback.process_ie_result(data, download=True)
                except DownloadError as exc2:
                    if is_hls_error(exc2):
                        logger.warning(
                            "Fallback download failed with HLS errors (%s). "
                            "Retrying with ffmpeg downloader.",
                            exc2,
                        )
                        try:
                            yt_dl_hls = YoutubeDL(
                                {
                                    **yt_dl_options,
                                    "format": fallback_format,
                                    "hls_prefer_native": False,
                                    "external_downloader": "ffmpeg",
                                    "external_downloader_args": ["-loglevel", "error"],
                                }
                            )
                            yt_dl_hls.process_ie_result(data, download=True)
                        except DownloadError as exc3:
                            logger.warning(
                                "Final download attempt failed (%s).", exc3
                            )
                            send_download_error(
                                "Failed to download resource. Try a different URL or retry later."
                            )
                            raise
                    else:
                        send_download_error(
                            "Failed to download resource. Try a different URL or retry later."
                        )
                        raise

        # TODO: Thread audio & video download

        audio_thread = None
        video_thread = None

        if not audio_downloaded:
            audio_source = select_source_file(temp_dir, media_id, prefer_video=False)
            if audio_source is None:
                logger.warning("Audio source file not found")
                run_coroutine_threadsafe(
                    resp.send(
                        dumps({"action": "error", "message": "Audio download failed."})
                    ),
                    loop,
                )
            else:
                from threading import Thread

                audio_thread = Thread(
                    target=download_audio, args=(audio_source, media_id, resp, loop)
                )
                audio_thread.start()

        if not video_downloaded and is_video:
            video_source = select_source_file(temp_dir, media_id, prefer_video=True)
            if video_source is None:
                logger.warning("Video source file not found")
                run_coroutine_threadsafe(
                    resp.send(
                        dumps({"action": "error", "message": "Video download failed."})
                    ),
                    loop,
                )
            else:
                if target_fps:
                    video_source = downsample_video(
                        video_source, media_id, resp, loop, target_fps
                    )
                from threading import Thread

                video_thread = Thread(
                    target=download_video,
                    args=(video_source, media_id, resp, loop, width, height),
                )
                video_thread.start()

        if audio_thread:
            audio_thread.join()
        if video_thread:
            video_thread.join()

    out = {
        "action": "media",
        "id": media_id,
        # "fulltitle": data.get("fulltitle"),
        "title": data.get("title"),
        "like_count": data.get("like_count"),
        "view_count": data.get("view_count"),
        "duration": data.get("duration"),
        # "upload_date": data.get("upload_date"),
        # "tags": data.get("tags"),
        # "description": data.get("description"),
        # "categories": data.get("categories"),
        # "channel_name": data.get("channel"),
        # "channel_id": data.get("channel_id")
    }

    # Only return playlist_videos if there are videos in playlist_videos
    if len(playlist_videos) > 0:
        out["playlist_videos"] = playlist_videos

    files = []
    files.append(get_audio_name(media_id))
    if is_video:
        files.append(get_video_name(media_id, width, height))

    return out, files
