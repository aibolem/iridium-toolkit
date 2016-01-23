# Simple toolkit to decode Iridium signals

### Requisites

 * Python (2.7)
 * NumPy (scipy)

### License

Unless otherwise noted in a file, everything here is
(c) Sec & schneider
and licensed under the 2-Clause BSD License

### Example usage
#### Capture with [hackrf](https://greatscottgadgets.com/hackrf/) or [rad1o](https://rad1o.badge.events.ccc.de/start) and multiprocessing

Note: The rad1o has to be in hackrf-mode

    hackrf_transfer -f 1625800000 -a 1 -l 40 -g 20 -s 2000000 -r /dev/fd3 3>&1 1>&2 | python2 extractor.py -c 1625800000 -r 2000000 -f hackrf --jobs 2 | fgrep "A:OK" >> output.bits

If you built/installed the rad1o branch of the hackrf tools, add `-S 26214400` to the commandine like this:

    hackrf_transfer -f 1625800000 -a 1 -l 40 -g 20 -s 2000000 -S 26214400 -r /dev/fd3 3>&1 1>&2 | python2 extractor.py -c 1625800000 -r 2000000 -f hackrf --jobs 2 | fgrep "A:OK" >> output.bits

This writes to `output.bits`. Pager messages can be decoded with

    python2 iridium-parser.py output.bits

if you want to speed up that step you can install `pypy` and instead run 

    pypy iridium-parser.py output.bits

### Extracting Iridium packets from raw data

To capture and demodulate Iridium packets use `extractor.py`. You can either process
a file offline or stream data into the tool.

#### Command line options:

##### `-o`, `--offline`: Process a file offline
By default, the extractor will drop samples if the computing power available is
not enough to keep up. If you have an already recorded file, use the `-o`,`--offline`
option to not drop any samples. In this case the extractor will pause reading the
file (or input stream) until it can process more samples again.

##### `-q`: Queue length
The internal queue is filled with samples where the detector has detected activity
in the file. By default it is 12000 elements long (roughly 4 GB at 2 Maps). You can
tweak the length of the queue with this option

##### `-c`: Center frequency
The center frequency of the samples data in Hz.

##### `-r`: Sample rate
The sample rate of the samples in sps

##### `-f`: Input file format
| File Format                                        | `extractor.py` format option |
|----------------------------------------------------|------------------------------|
| complex uint8 (RTLSDR)                             | `rtl`                        |
| complex int8 (hackrf, rad1o)                       | `hackrf`                     |
| complex int16 (USRP with specrec from gr-analysis) | `sc16`                       |
| complex float (GNURadio, `uhd_rx_cfile`            | `float`                      |

##### `-j`, `--jobs`
The number of processes to spawn which demodulate packets. The detector runs in the main
process.

### Main Components

#### Detector
`detector-fft.py`

Searches through the file in 1 ms steps to scan for activity
and copies these parts into snippets called `<rawfilename>-<timestamp>.det`

#### Cut and Downmix

`cut-and-downmix.py`

Mixes the signal down to 0 Hz and cuts the beginning to match
the signal exactly. Output is `<detfile>-f<frequency>.cut`

#### Demod

`demod.py`

Does manual DQPSK demodulation of the signal and outputs
`<cutfile>.peaks` (for debugging)
`<cutfile>.data` the raw bit stream
and on stdout an ASCII summary line.

#### Parser

`iridium-parser.py`

Takes the demodulated bits and tries to parse them into a readable format.

Supports some different output formats (`-o` option).

