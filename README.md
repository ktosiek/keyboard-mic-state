# "On Air" mode for Keyboardio Model01 / Kaleidoscope

This script makes sure your keyboard shows that a mic is open.

Usage:

1. Flash firmware with the FocusLEDCommand plugin enabled (it's not enabled by default).
2. Run `pipenv install`.
3. Set MIC_MUTE_KEY in main.py to the key index for the On Air button (for me it's prog, number 3).
4. Set MIC_ACTIVE_LED_MODE to the LED mode you want to use when on air (the default should work well, it can't be a mode
   that sets the color for MIC_MUTE_KEY).
5. Run `pipenv run main`! If any mic is open the keyboard should turn black, with one red LED.
