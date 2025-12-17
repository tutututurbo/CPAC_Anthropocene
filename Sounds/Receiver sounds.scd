// Starting the server
s.reboot;

// Receiver
NetAddr("127.0.0.1",12000);

// Global variable to map the number of people
~lastN = 0;

// Where to take the sound files
(
~soundPath = "C:/Users/HP/Downloads/ProgettoCPAC/";
~files = [
    "Stickz-RiseBirdsFX1.wav",
    "Stickz-RiseBirdsFX2.wav",
    "citadel_datatransmission01_loop.wav",
    "citadel_citadel_sickcore_loop5.wav",
    "canals_windmill_wind_loop1.wav",
];

~buffers = ~files.collect { |f|
    Buffer.read(s, ~soundPath ++ f);
};
)

// Play Buffer Synth
(
SynthDef(\playBuf, { |buf, amp = 0.2|
    var sig;
    sig = PlayBuf.ar(
        numChannels: ,
        bufnum: buf,
        rate: BufRateScale.kr(buf),
        doneAction: 2
    );
    Out.ar(0, sig * amp);
}).add;
)

(
~playNSounds = { |n|
    n = n.clip(0, ~buffers.size); // sicurezza

    ~buffers
        .scramble
        .keep(n)
        .do { |buf|
            Synth(\playBuf, [
                \buf, buf,
                \amp, 0.15
            ]);
        };
};
)

// OSC Receiver
// Takes the number of people involved and if it is different from the previous
// iteration it triggers the function
(
OSCdef(\receiveNumber, { |msg|
    var n;
    n = msg[1].asInteger;

    // Controllo: esegui solo se il valore è cambiato
    if (~lastN.isNil or: { n != ~lastN }) {
        ("Ricevuto nuovo numero: " ++ n).postln;
        ~playNSounds.(n);
        ~lastN = n;  // aggiorna lo stato
    } {
        ("Numero invariato: " ++ n ++ " → nessuna azione").postln;
    };

}, '/n_of_persons', recvPort: 12000);
)