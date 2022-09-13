from pydantic import BaseSettings

#TODO add documentation

class StableDiffusion(BaseSettings):
        max_steps: int = 85
        max_itterations: int = 1

class Reporting(BaseSettings):
        calculate_skin: bool = True

class RedisKeys(BaseSettings):
        # The experation time of 'dreaming-working', 
        # can be set to something low.
        working_exp:int = 300
        # When a job should expire from redis
        # Set this to something not too low.
        job_exp:int = 3600 


class Settings(BaseSettings):
   sentry_sdk: str = ""
   redis_url: str = "redis://localhost:6379/0?encoding=utf-8"
   sd_url: str= "http://localhost:9090/"
   
   redisKeys = RedisKeys()
   stableDiffusion = StableDiffusion()
   reporting = Reporting()

   class Config:
        env_file = ".env"

settings = Settings()