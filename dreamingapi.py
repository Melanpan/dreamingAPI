import os
import io
import uuid
import json
import time
import asyncio
import logging
import sentry_sdk
import coloredlogs

import api.redisClass as redisClass
import api.backgroundWorker as backgroundWorker
import api.stableDiffusionComunicator as stableDiffusionComunicator

from PIL import Image
from config import settings
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException, Response, Request, Form
from fastapi.responses import StreamingResponse, PlainTextResponse, HTMLResponse

# Setup logging
logging.config.fileConfig('logging.conf', disable_existing_loggers=False)
logging.getLogger("uvicorn.access").setLevel(logging.WARN)
logger = logging.getLogger(__name__)
coloredlogs.install(level='INFO', logger=logger)

# Setup classes
redis = redisClass.redisClass()
client = stableDiffusionComunicator.communicator()
background = backgroundWorker.backgroundWorkerClass(redis=redis, client=client)

# Setup sentry, if enabled
if settings.sentry_sdk != "":
    sentry_sdk.init(settings.sentry_sdk, traces_sample_rate=1.0)

# Setup fastapi
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware( CORSMiddleware, allow_origins=["*"], 
        allow_credentials=True, allow_methods=["*"], 
        allow_headers=["*"])

async def getJobPos(uuid:str) -> dict:
    """ Return the job position of uid, as well as the total items
        in the queue and if we are currently working on something. """
    matchingJobPos = -1
    pos = 0
    queue = [json.loads(job) for job in await redis.lrange("sd-queue")]

    for job in reversed(queue):
        if job['uuid'] == uuid:
            matchingJobPos = pos
        pos += 1

    if len(queue) >= 1:
        return {"pos": matchingJobPos + 1, "total": len(queue) + 1, "working": background.working}
    return {"pos": 0, "total": 0, "working": background.working}

async def interfaceStreamer(uuid):
    """ Stream every event as a new line, in json format. 
        Exactly how the stable diffusion web interface handles it
        So that we can just use that with minimial modding instead
        of making our own.
    """
    while True:
        job = await redis.get(f"dreaming-job-{uuid}")
        if not job:
            yield json.dumps({"event": "error", "message": f"Failed to find uuid {uuid}"}) + "\n"
            return

        # Add GPU info to the output
        job.update({"jobpos": await getJobPos(uuid),
            "gpu": {
                "temp": background.smi['nvidia_smi_log']['gpu']['temperature']['gpu_temp'],
                "power": background.smi['nvidia_smi_log']['gpu']['power_readings']['power_draw'],
                "util": background.smi['nvidia_smi_log']['gpu']['utilization']['gpu_util'],
                "pci": {
                    "tx_util": background.smi['nvidia_smi_log']['gpu']['pci']['tx_util'],
                    "rx_util": background.smi['nvidia_smi_log']['gpu']['pci']['rx_util'],
                }
            }})
        
        if "initimg" in job:
            job.pop("initimg") # Don't send back base64 data to the client

        if job['event'] == "canceled": 
            yield json.dumps(job) + "\n"
            break

        if job['event'] == "done": 
            # Make the response into something how
            # the web interface wants it
            job['event'] = "result"
            job.update(job['result'])
            job.pop('result') # Remove result and raw, the client does not like a lot of data at once
            job.pop('raw')
            yield json.dumps(job) + "\n"
            break
        else:
            if job['event'] == "generating":
                job['event'] = "step"
            
            yield json.dumps(job) + "\n"
        await asyncio.sleep(1.00)

def calculateResponseTimes() -> float:
    """ Calculates the average response times """
    responseTime = 0
    for resptimeEntry in client.responseTimes:
        responseTime += resptimeEntry
    
    if responseTime == 0:
        return 0.0
    
    return round((responseTime / len(client.responseTimes)), 3)

def imageAsJpeg(image_path: str) -> io.BytesIO:
    """ Convert an image in-memory to jpeg and return a bytesio"""
    img = Image.open(image_path).convert("RGB")
    ioimg = io.BytesIO()
    img.save(ioimg, format="jpeg")
    ioimg.seek(0)
    return ioimg

@app.on_event('startup')
async def startup_event():
    """ Initialize async functions on startup"""
    await redis.init()
    await client.init()
    await background.init()

@app.on_event('shutdown')
async def shutdown_event():
    """ Initialize async functions on startup"""
    if background.working:
        print("Waiting for job to finish...")
        while background.working:
            await asyncio.sleep(0.10)

    await client.client.close()
    logging.warning("Gracefully exiting... Good-bye!")

@app.get("/job/get")
async def get_job(uuid: str):
    """ Returns the job straight from Redis """
    if job := await redis.get(f"dreaming-job-{uuid}"):
        if job['event'] == "queued":
            job['queue'] = await getJobPos(uuid)
        return job
    raise HTTPException(status_code=404, detail="UUID not found")

@app.get("/job/cancel")
async def get_job(uuid: str):
    """ Returns the job straight from Redis """
    
    if job := await redis.get(f"dreaming-job-{uuid}"):
        if background.workingUuid == uuid:
            background.jobCanceled = True
        else:
            await redis.delete(f"dreaming-job-{uuid}")
        return {"status": f"OK"}
    
    raise HTTPException(status_code=404, detail="UUID not found")


@app.get("/job/delete")
async def delete_job(uuid: str):
    """ Remove a job from the queue"""
    await redis.delete(f"dreaming-job-{uuid}")
    return {"status": f"OK"}

@app.get("/job/list")
async def list_jobs():
    """ List all jobs in the qeueue """
    jobs = []
    for pos, job in enumerate(await redis.lrange("sd-queue")):
        jobs.append({"job": json.loads(job), "pos": pos})
    return jobs

@app.get("/status")
async def list_jobs():
    """ Return some status information """
    return {"status": await redis.get("dreaming-status"), 
            "working": await redis.get("dreaming-working"),
            "nvidia": background.smi, "queuesize": len(await redis.lrange('sd-queue'))}

@app.get("/gpu") #TODO change path
async def gpu_info():
    """ Return nvidia-smi data as json"""
    return background.smi

@app.get("/telegraf", response_class=PlainTextResponse)
async def telegraf():
    """ Return a influxDB status line for Telegraf. """
    stats = await redis.get("sd-stats")
    await redis.delete("sd-stats")
    if stats:
        stats = json.loads(stats)
        return f"dreaming skin={stats['skin']},charlen={stats['charlen']},processtime={stats['processtime']},queuesize={len(await redis.lrange('sd-queue'))}"
    return f"dreaming skin=0.0,charlen=0,processtime=0,queuesize=0"

@app.get("/job/image")
async def job_image(uuid: str, jpeg: bool | None = False):
    """ Return a generatd image based on the uuid, if jpeg is set to true it will return it as jpeg """
    # For the time being, we can only handle single files
    if job := await redis.get(f"dreaming-job-{uuid}"):
        if not "result" in job:
            raise HTTPException(status_code=404, detail="Job is likely still being generated. Please see /job/get")
        
        # throw error if image doesn't exist
        imagePath = os.path.join("/home/nurds/stable-diffusion/outputs/img-samples", os.path.basename(job['result']['url']))
    
        if not os.path.exists(imagePath):
            raise HTTPException(status_code=404, detail="Failed to find generate image locally.")
        
        if jpeg:
            return Response(imageAsJpeg(imagePath).read(), media_type="Image/Jpeg")
        else:
            with open(imagePath, "rb") as f:
                return Response(f.read(), media_type="Image/PNG")
    
    return {"error": f"Couldn't find a job with uuid {uuid}"} #change to 404

#TODO code me better
@app.get("/job/image/intermediates")
async def job_image_inter(image):
    imagePath = os.path.join("/home/nurds/stable-diffusion/outputs/img-samples/intermediates/", image)
    with open(imagePath, "rb") as f:
            return Response(f.read(), media_type="Image/PNG")

@app.get("/job/jpg")
async def job_image(uuid: str):
    # For the time being, we can only handle single files
    if job := await redis.get(f"dreaming-job-{uuid}"):
        if not "result" in job:
            return {"error": "Job is likely still being generated. Please see /job/get"}
        # throw error if image doesn't exist
        imagePath = os.path.join("/home/nurds/stable-diffusion/outputs/img-samples", os.path.basename(job['result']['url']))
    
        if not os.path.exists(imagePath):
            return Response(status_code=404)
        
        return Response(imageAsJpeg(imagePath).read(), media_type="Image/Jpeg")

def parseStringToBool(input: str) -> bool:
    if input == 'on':
        return True
    return False

@app.post("/dream")
async def do_dream(request: Request):
    job = await request.json()
    
    jobuuid = str(uuid.uuid1())
    
    job.update({"uuid": jobuuid, "initiator": "api", "event": "queued", "timestamp": time.time()})
    
    await redis.setex(f"dreaming-job-{job['uuid']}", job, 12000)
    await redis.lpush("sd-queue", job)
    
    job.update({"queuepos": await getJobPos(jobuuid)})
    return {"status": "OK", "uuid": job['uuid'], "job": job}

# TODO refactor
@app.post("/dreamSIMPLE", response_class=HTMLResponse)
async def do_dreamSIMPLE(prompt: str = Form(), cfg_scale: str = Form(), steps: str = Form(), seed: str = Form(), 
                         sampler_name: str = Form(), strength: str = Form(), gfpgan_strength: str = Form(), 
                         upscale_level: str = Form(), upscale_strength: str = Form()):
    fakejson = {}
    fakejson['prompt'] = prompt
    fakejson['cfg_scale'] = cfg_scale
    fakejson['steps'] = steps
    fakejson['seed'] = seed
    fakejson['sampler_name'] = sampler_name
    fakejson['strength'] = strength
    fakejson['gfpgan_strength'] = gfpgan_strength
    fakejson['upscale_level'] = upscale_level
    fakejson['upscale_strength'] = upscale_strength

    job = fakejson
    jobuuid = str(uuid.uuid1())
    
    job.update({"uuid": jobuuid, "initiator": "api", "event": "queued", "timestamp": time.time()})
    
    await redis.setex(f"dreaming-job-{job['uuid']}", job, 12000)
    await redis.lpush("sd-queue", job)
    
    job.update({"queuepos": await getJobPos(jobuuid)})
    returntxt = """
        <a href="http://10.208.30.24:8000/job/jpg?uuid={0}">click in about 1 minute</a>
        <a href="http://10.208.30.24:8000/job/get?uuid={0}">or check on status here</a>
    """
    return HTMLResponse(content=returntxt.format(job['uuid']), status_code=200)

@app.post("/")
async def dreamStreaming(request: Request):
    
    job = await request.json() # Web interface sends parameters as json
    job.update({"uuid": str(uuid.uuid1()), "initiator": "web", "event": "queued", "timestamp": time.time()})
    job.pop("initimg_name")

    job['fit'] = parseStringToBool(job['fit'])
    if "progress_images" in job:
        job['progress_images'] = parseStringToBool(job['progress_images'])

    await redis.setex(f"dreaming-job-{job['uuid']}", job, 12000)
    await redis.lpush("sd-queue", job)
    
    return StreamingResponse(interfaceStreamer(uuid=job['uuid']))

@app.get("/") 
async def serveIndex():
    with open("static/index.html", "rb") as f:
        return Response(f.read(), media_type="text/html")
