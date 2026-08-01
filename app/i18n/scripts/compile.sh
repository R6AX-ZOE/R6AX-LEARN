#!/bin/bash
set -e

echo "Compiling translations..."
pybabel compile -d app/i18n/locales

echo "Done!"
