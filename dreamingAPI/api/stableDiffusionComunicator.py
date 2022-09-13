import json
import time
import logging
import logging
import aiohttp

from config import settings

logger = logging.getLogger(__name__)

class communicator():
    responseTimes = []
    currentJobTime = 0

    async def init(self):
        self.client = aiohttp.ClientSession()

    async def request(self, prompt, sampler_name ="k_lms", width=512, height=512, initimg=None, 
                      cfg_scale=7, steps=50, iterations=1, seed=-1, strength=0.75,
                      gfpgan_strength=0.8, upscale_level=2, upscale_strength=0.75, fit="on"):
        
        options = locals()
        options.pop("self")

        # Limit steps and iterations as defined in config.py
        if int(options['steps']) > settings.stableDiffusion.max_steps:
            options['steps'] = settings.stableDiffusion.max_steps
        
        if int(options['iterations']) > settings.stableDiffusion.max_itterations:
            options['iterations'] = settings.stableDiffusion.max_itterations

        if options['seed'] == "":
            options['seed'] = "-1"
                
        async with self.client.post(settings.sd_url, json=options) as resp:
            options.pop('initimg') # Don't print this into the log
            logging.info(f"Request to {settings.sd_url} ({options})")

            startTime = time.time()

            if resp.status == 200:
                buffer = b""
                """ The lstein Stable Diffusion fork returns a new status line in as a stream."""
                while True:
                    
                    if resp.content.at_eof(): # End of line, job done
                        self.responseTimes.append(time.time() - startTime)
                        self.currentJobTime = time.time() - startTime
                        self.log.info(f"Job done! Took {self.currentJobTime} ms")

                        if len(self.responseTimes) > 10:
                            self.responseTimes.pop(0)
                        return
                    
                    else:
                        respBytes = await resp.content.read(1)
                        buffer += respBytes

                    if buffer.endswith(b"\n"):
                          yield json.loads(buffer)
                          buffer = b""
            else:
                logging.error(f"Request to {settings.sd_url} failed! Got status code of {resp.status} ({options})")
                yield {"error": f"Stable Diffusion API end-point returned a http-status code of {resp.status}"}

            return