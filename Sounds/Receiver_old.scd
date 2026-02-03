// Starting the server
s.reboot;

// Receiver
NetAddr("127.0.0.1",57120);

// Global variable to map the number of people
~lastN = 0;

// Where to take the sound files, directory has to be changed
// All files are stereo by default
(
~soundPath = "Layers/";
~files = [
    "1.mp3",
    "2.mp3",
    "3.mp3",
    "4.mp3",
    "5.mp3",
    "6.mp3"
];

~buffers = ~files.collect { |f|
    Buffer.read(s, ~soundPath ++ f);
};
)

// Layer Player Synth: the main idea is to play all layers
// together and scale the amplitude of each one depending on the number
// of people present in the room
(
SynthDef(\layerPlayer, { |buf, amp = 0, out = 0|
    var sig;
    sig = PlayBuf.ar(
        2,
        buf,
        BufRateScale.kr(buf),
        loop: 1
    );
    sig = sig * Lag.kr(amp, 1.5); // fade smooth
    Out.ar(out, sig);
}).add;
)

// Where to locate all layers
(
~layers = ~buffers.collect { |buf|
    Synth(\layerPlayer, [
        \buf, buf,
        \amp, 0
    ]);
};
)

// Update in amplitude of each layer, if n increases
// preavious layers will go down in amplitude, if n
// decreases volumes will go up accordingly
(
~updateLayers = { |n|
    n = n.clip(0, ~layers.size);

    ~layers.do { |synth, i|
        var distance, amp;

        if (i < n) {
            distance = (n - 1) - i;
            amp = 1 / (distance + 1);
        } {
            amp = 0;
        };

        synth.set(\amp, amp);
    };
};
)


// OSC Receiver
// Takes the number of people involved and if it is different from the previous
// iteration it triggers the function updateLayers
(
OSCdef(\receiveNumber, { |msg|
    var n = msg[1].asInteger;

    if (n != ~lastN) {
        ("Persone: " ++ n).postln;
        ~updateLayers.(n);
        ~lastN = n;
    };

}, '/entropy_level', recvPort: 57120);
)
