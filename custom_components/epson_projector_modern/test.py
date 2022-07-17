#!/usr/bin/env python3

import argparse
import asyncio
import logging
import sys

from projector import Projector

cli_parser = argparse.ArgumentParser()
cli_parser.add_argument('--host', help='panel hostname')

args = cli_parser.parse_args()

logging.basicConfig(stream = sys.stdout,
                    format='%(levelname)s: %(message)s',
                    level = logging.DEBUG)

async def main():
    p = Projector(args.host)
    await p.connect()
    p.log_state()
    await asyncio.sleep(3)
    await p.set_power(True)
    await p.set_source('HDMI1')
    await asyncio.sleep(3)
    p.log_state()
    await asyncio.sleep(3)
    await p.set_source('HDMI2')
    await p.set_power(True)
    await p.set_source('HDMI1')
    p.log_state()
    await asyncio.sleep(30)
    await p.disconnect()

asyncio.run(main())



