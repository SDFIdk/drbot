# DRBOT

DRBOT is a geodatabase bot for running Esri's Data Reviewer.

This Python script executes one or more .rbj files, writes the result
into a DR enabled gdb, and optionally sends an email summarizing the
findings. It works both with ArcMap and ArcGIS Pro (Python 2.7 and 3).

In command line mode it can be useful for running scheduled data
monitoring, or simply as a wrapper that handles session setup etc. if
you want to run Data Reviewer from Python. I've also included a basic
Python toolbox for running the tool interactively. You probably want to
modify the tool setup to offer an appropriate selection of validation
files for your users.

The code is not a clean and streamlined as it could be, but it works ok
for our purposes and can hopefully still be helpful and/or
inspirational.
