#!/bin/zsh
cd -- "${0:A:h}" || exit 1
python3 server.py
read -r "?Pulsa Intro para cerrar."
