## DEPRECATED in favour of much more complete [ha-epson-projector-link](https://github.com/amosyuen/ha-epson-projector-link) integration.

A Home Assistant integration to control modern Epson projectors.

It has the following key differences compared to the [built-in Epson integration](https://www.home-assistant.io/integrations/epson/), based on the [pszafer/epson_projector](https://github.com/pszafer/epson_projector/tree/dev/epson_projector) library:
 - it works (only) with modern Epson projector models, like the LS11000 and LS12000
 - it uses a persistent TCP connection
 - it is event diven (not polling)
