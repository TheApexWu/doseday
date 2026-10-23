#!/usr/bin/env python3
import asyncio

from viam.module import Module

import model  # noqa: F401 - importing registers the model


if __name__ == "__main__":
    asyncio.run(Module.run_from_registry())
