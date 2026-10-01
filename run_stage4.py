#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/youtubr_clipper/src')
from run_pipeline import main
sys.argv = ['run_pipeline', 'https://youtu.be/S-7VkwSU0gs?si=rtT2M4H2YwN9G189', '--from-stage', '4']
main()