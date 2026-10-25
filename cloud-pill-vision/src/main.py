import asyncio
from viam.module.module import Module
from models.cloud_pill_detector import CloudPillDetector as CloudPillDetectorModel


if __name__ == '__main__':
    asyncio.run(Module.run_from_registry())
