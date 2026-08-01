#!/bin/bash
set -e

echo "Extracting messages from templates and source files..."
pybabel extract -F babel.cfg -o app/i18n/locales/messages.pot .

echo "Updating existing translations..."
pybabel update -i app/i18n/locales/messages.pot -d app/i18n/locales

echo "Done!"
