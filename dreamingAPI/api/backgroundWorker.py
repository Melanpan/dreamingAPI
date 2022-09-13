import asyncio
import json
import logging
import subprocess
import xmltodict
import copy
import os
import api.skinDetector as skinDetector
from config import settings
from sentry_sdk import capture_exception

# TODO proper error detection
# TODO ability to cancel
# TODO set paths in env

class backgroundWorkerClass():
    smi = None
    working = False
    workingUuid = None

    def __init__(self, redis, client) -> None:
        self.redis = redis
        self.client = client
    
    async def init(self):
        asyncio.create_task(self.workerTask())
        asyncio.create_task(self.nvidiaSmiTask())

    def getNvidiaSmi(self):
        try:
            info = subprocess.check_output(["/usr/bin/nvidia-smi", "-x", "-q"], stderr=subprocess.STDOUT)
            return xmltodict.parse(info.decode("utf8"))
        except Exception as e:
            logging.error(f"Failed to xecute nvidia-smi! ({e})")
            return f"Executing nvidia-smi failed: {e}"

    async def jobprocessRespline(self, respLine, job):
        """ Process a line as return by lstein's Stable Diffusion api"""
        await self.redis.setex("dreaming-status", {"uuid": job['uuid'], "status": respLine}, 
                                settings.redisKeys.working_exp)

        # Update the job dictionary with the current state
        if "event" in respLine and respLine['event'] == "step":
            job['event'] = "generating"
            job['step'] = respLine['step']
       
        elif "event" in respLine and respLine['event'].startswith("upscaling"):
            job['event'] = respLine['event']
            job['step'] = 0

        await self.redis.setex(f"dreaming-job-{job['uuid']}", 
            job, settings.redisKeys.job_exp)
        return job

    async def execute(self, job):
        self.working = True
        self.workingUuid = job['uuid']
        
        results = {}
        promptBuffer = []
        
        logging.info(f"Working on: {job['prompt']} ({job['uuid']})")
        await self.redis.setex("dreaming-working", 
            job['uuid'], settings.redisKeys.working_exp)
        
        request_parameters = copy.deepcopy(job)
        # Remove parameters that we don't need
        for parameter in ['event', 'uuid', 'initiator', 'timestamp']:
            request_parameters.pop(parameter)
        
        async for respLine in self.client.request(**request_parameters):
            promptBuffer.append(respLine)
            job = await self.jobprocessRespline(respLine, job)
             
            if "event" in respLine and respLine['event'] == "result":
                results = respLine
        
        job['event'] = "done"
        job['raw'] = promptBuffer
        job['result'] = results
        
        await self.redis.setex(f"dreaming-job-{job['uuid']}", job, 3000) # Job result will expire in a hour
        
        # Set back to default
        await self.redis.delete("dreaming-working")
        await self.redis.set("dreaming-status", {"status": "Awaiting prompts."})
        
        # detect skin if enabled
        skinAmount = 0
        if settings.reporting.calculate_skin == True:
            skinAmount = skinDetector.skinDetect(image=os.path.join("/home/nurds/stable-diffusion/outputs/img-samples", os.path.basename(job['result']['url']))).detect()
        
        # Stats
        statsJson = {
            "skin": round(skinAmount, 3), 
            "charlen": len(job['prompt']),
            "processtime": round(self.client.currentJobTime, 3), 
            }
        
        await self.redis.set("sd-stats", json.dumps(statsJson))

        logging.info(f"Finished working on: {job['prompt']} ({job['uuid']})")
        self.working = False
        self.workingUuid = None

    async def nvidiaSmiTask(self):
        logging.info("Starting nvidia-smi background task")
        while True:
            self.smi = await asyncio.get_event_loop().run_in_executor(None, self.getNvidiaSmi)
            await asyncio.sleep(1)

    async def workerTask(self):
        logging.info("Starting background worker task")
        await self.redis.set("dreaming-status", {"status": "Awaiting prompts."})

        # Grab a job from the queue
        while True:
            if job := await self.redis.rpop("sd-queue"):
                try:
                    await self.execute(job)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    self.log.error(f"An exception occured in the background thread! {e}")
                    capture_exception(e)

            await asyncio.sleep(0.100)