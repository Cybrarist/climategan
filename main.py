import shutil
from pprint import pprint

import cv2
import imageio
from dash.dependencies import extract_grouped_output_callback_args
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles
from typing import List, Optional
from pathlib import Path
from shutil import  rmtree
import zipfile
import subprocess
import uuid

app = FastAPI()


ALLOWED_MIME_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif"}
BASE_TEMP_DIR = Path("temp")
BASE_TEMP_DIR.mkdir(exist_ok=True)

@app.post("/submit_images")
async def submit_images(
    images: List[UploadFile] = File(...),
    batch_size: int = Form(4),
    target_size: int = Form(640),
    max_im_width: int = Form(-1),
    no_time: Optional[bool] = Form(False),
    half: Optional[bool] = Form(False),
    no_cloudy: Optional[bool] = Form(False),
    fuse: Optional[bool] = Form(False)
):
    if target_size < 128 or target_size % 128 != 0:
        raise HTTPException(status_code=400, detail="Target size must be a multiple of 128 and >= 128")

    unique_id = uuid.uuid4().hex[:8]
    upload_dir = BASE_TEMP_DIR / f"upload_{unique_id}"
    output_dir = BASE_TEMP_DIR / f"output_{unique_id}"
    upload_dir.mkdir()

    saved_files = []
    try:
        for image in images:
            if image.content_type not in ALLOWED_MIME_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid file type: {image.filename}")

            ext = ALLOWED_MIME_TYPES[image.content_type]
            new_name = f"{uuid.uuid4().hex}.{ext}"
            dest = upload_dir / new_name

            with dest.open("wb") as f:
                content = await image.read()
                f.write(content)

            saved_files.append(dest)

        cmd = [
            ".venv/bin/python3",
            "apply_events.py",
            "-b", str(batch_size),
            "--target_size", str(target_size),
            "-i", str(upload_dir),
            "-r", "config/model/masker",
            "--output_path", str(output_dir)
        ]

        if no_time: cmd.append("--no_time")
        if half: cmd.append("--half")
        if no_cloudy: cmd.append("--no_cloudy")
        if fuse: cmd.append("--fuse")
        if max_im_width != -1:
            cmd.extend(["--max_im_width", str(max_im_width)])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Processing script failed: {result.stderr}")

        zip_path = BASE_TEMP_DIR / f"results_{unique_id}.zip"
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for file_path in output_dir.iterdir():
                zipf.write(file_path, arcname=file_path.name)

        return FileResponse(zip_path, filename=zip_path.name)

    finally:
        print("Cleaning up...")
        # for f in saved_files:
        #     f.unlink(missing_ok=True)
        # if upload_dir.exists():
        #     rmtree(upload_dir)
        # if output_dir.exists():
        #     rmtree(output_dir)


@app.post("/submit_video")
async def submit_video(
    video: UploadFile = File(...),
    batch_size: int = Form(4),
    target_size: int = Form(640),
    max_im_width: int = Form(-1),
    no_time: bool = Form(False),
    half: bool = Form(False),
    no_cloudy: bool = Form(False),
    fuse: bool = Form(False)
):
    if target_size < 128 or target_size % 128 != 0:
        raise HTTPException(status_code=400, detail="Target size must be a multiple of 128 and >= 128")

    unique_id = uuid.uuid4().hex[:8]
    session_dir = BASE_TEMP_DIR / f"session_{unique_id}"
    upload_dir = BASE_TEMP_DIR / f"upload_{unique_id}"
    output_dir = BASE_TEMP_DIR / f"output_{unique_id}"
    upload_dir.mkdir()
    session_dir.mkdir()

    video_path = upload_dir / "input_video.mp4"
    with open(video_path, "wb") as f:
        f.write(await video.read())

    try:
        # Step 1: Extract frames
        vidcap = cv2.VideoCapture(str(video_path))
        frame_paths = []
        frame_count = 0
        frames = []
        success, frame = vidcap.read()




        while success:
            frame_name = f"frame_{frame_count:06d}.png"
            frame_path = upload_dir / frame_name
            if frame_count % 3 == 0:
                height, width = frame.shape[:2]
                resized_frame = cv2.resize(frame, (width // 2, height // 2), interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(frame_path), resized_frame)
                frame_paths.append(frame_path)
                frames.append(frame_path)
            frame_count += 1
            success, frame = vidcap.read()
        vidcap.release()

        print("finished video processing")



        if frame_count == 0:
            raise HTTPException(status_code=400, detail="No frames extracted from video.")

        # Step 2: Process frames in batches of 100
        num_batches = (frame_count + 99) // 100
        for i in range(num_batches):
            print(f"processing batch {i+1}/{num_batches}")
            batch_input_dir = session_dir / f"batch_{i:03d}_input"
            batch_output_dir = session_dir / f"batch_{i:03d}_output"
            batch_input_dir.mkdir()

            batch_frames = frames[i * 100:(i + 1) * 100]
            for frame_path in batch_frames:
                shutil.copy(frame_path, batch_input_dir / frame_path.name)

            cmd = [
                ".venv/bin/python3", "apply_events.py",
                "-b", str(batch_size),
                "--target_size", str(target_size),
                "-i", str(batch_input_dir),
                "-r", "config/model/masker",
                "--output_path", str(batch_output_dir)
            ]
            if no_time: cmd.append("--no_time")
            if half: cmd.append("--half")
            if no_cloudy: cmd.append("--no_cloudy")
            if fuse: cmd.append("--fuse")
            if max_im_width != -1:
                cmd.extend(["--max_im_width", str(max_im_width)])

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise HTTPException(status_code=500,
                                    detail=f"Processing script failed on batch {i}: {result.stderr}")

                # Step 3: Combine all processed frames
            all_output_frames = []

            types = ['flood', 'smog', 'wildfire']

            for singleType in types:
                all_output_frames = []  # Reset for each type
                print(singleType)
                for j in range(num_batches):
                    batch_output_dir = session_dir / f"batch_{j:03d}_output"
                    all_output_frames.extend(sorted(batch_output_dir.glob(f"frame_*_{singleType}_*.png")))

                if not all_output_frames:
                    raise HTTPException(status_code=500, detail="No output frames found after processing.")

                type_video_path = session_dir / f"{singleType}_{unique_id}.mp4"
                writer = imageio.get_writer(str(type_video_path), fps=24)
                for frame_path in all_output_frames:
                    writer.append_data(imageio.imread(str(frame_path)))
                writer.close()

            # Create zip file with all videos
            print(f'session_dir / f"videos_{unique_id}.zip"')
            zip_path = session_dir / f"videos_{unique_id}.zip"
            with zipfile.ZipFile(zip_path, "w") as zipf:
                for singleType in types:
                    video_path = session_dir / f"{singleType}_{unique_id}.mp4"
                    if video_path.exists():
                        zipf.write(video_path, arcname=video_path.name)

            return FileResponse(zip_path, filename=zip_path.name)

    finally:
        print("cleanibng")
        # if upload_dir.exists():
        #     rmtree(upload_dir)
        # if output_dir.exists():
        #     rmtree(output_dir)


app.mount("/", StaticFiles(directory="site", html=True, check_dir=False), name="site")
