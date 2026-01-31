s.reboot;

// Receiver
NetAddr("127.0.0.1",57120);

// Global variable to map the number of people
~lastN = 0;

//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
// Path e Buffers
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
(
// Nota: Usa slash normali "/" per evitare problemi di escape su Windows
~soundPath = "C:/Users/filop/Desktop/CPaC/ANTHROPOCENE/layers/";
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
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
// PLAYER
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
(
// 1. Layer Player Standard
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

// 2. Layer Player Granulare (NUOVO)
SynthDef(\granularPlayer, { |buf, amp = 0, out = 0, density = 25, dur = 0.15|
    var sig, trig, pos;

    // Genera trigger per i grani
    trig = Impulse.ar(density);

    // Posizione "erratica" nel file (scanning lento con jitter)
    pos = LFNoise1.kr(0.1).range(0, 1);

    sig = TGrains.ar(
        2,              // Stereo
        trig,           // Trigger
        buf,            // Buffer
        1,              // Rate (1 = normale)
        pos * BufDur.kr(buf), // Posizione in secondi
        dur,            // Durata grano
        0,              // Pan
        0.5             // Amp grano singolo
    );

    // Filtro passa alto per pulire il mix
    sig = HPF.ar(sig, 200);

    // Lag lento (3s) per entrare in modo inquietante
    sig = sig * Lag.kr(amp, 3.0);
    Out.ar(out, sig);
}).add;
)
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
// ARRAYS
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
(
// Array Standard
~layers = ~buffers.collect { |buf|
    Synth(\layerPlayer, [
        \buf, buf,
        \amp, 0
    ]);
};

// Array Granulare (parte a volume 0)
~granLayers = ~buffers.collect { |buf|
    Synth(\granularPlayer, [
        \buf, buf,
        \amp, 0
    ]);
};
)
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
// STANDARD VS GRANULAR
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
(
~updateLayers = { |n|
    var granIntensity;

    n = n.clip(0, ~layers.size);

    // Definiamo quanto "forte" deve essere l'influenza dei grani
    // Questo valore si SOMMA al volume normale, non lo sostituisce.
    granIntensity = case
        { n <= 3 } { 0.0 }  // Nessun grano
        { n == 4 } { 0.3 }  // Presenza sottile
        { n == 5 } { 0.5 }  // Presenza media
        { n == 6 } { 0.8 }; // Molto presente (quasi quanto il segnale dry)

    // --- 1. LIVELLO BASE (Standard) ---
    // Questo rimane "solido". Il volume è calcolato sulla distanza come prima.
    ~layers.do { |synth, i|
        var distance, amp;

        if (i < n) {
            distance = (n - 1) - i;
            // Formula originale: 1/1, 1/2, 1/3...
            amp = 1 / (distance + 1);
        } {
            amp = 0;
        };

        synth.set(\amp, amp);
    };

    // --- 2. LIVELLO GRANULARE (Texture/Caos) ---
    // Si aggiunge sopra al livello base per i file n-1 e n-2
    ~granLayers.do { |gsynth, i|
        var gAmp = 0;

        // Logica attiva solo da 4 in su
        if (n >= 4) {
            // Seleziona il layer corrente (n-1) o il precedente (n-2)
            if ( (i == (n-1)) || (i == (n-2)) ) {
                // Qui applichiamo l'intensità calcolata all'inizio
                gAmp = granIntensity;
            };
        };

        gsynth.set(\amp, gAmp);
    };

    if(n >= 4) {
        ("Livello " + n + ": Base al 100% + Granulare a " + granIntensity).postln;
    };
};
)
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
// OSC RECEIVER
//////////////////////////////////////////////////////
//////////////////////////////////////////////////////
(
OSCdef(\receiveNumber, { |msg|
    var n = msg[1].asInteger;

    if (n != ~lastN) {
        ("Persone/Entropia: " ++ n).postln;

        // Debug visivo per capire cosa sta succedendo
        if (n >= 4) {
            (">> ATTIVAZIONE GRANULARE SUI LIVELLI: " ++ (n) ++ " e " ++ (n-1)).postln;
        };

        ~updateLayers.(n);
        ~lastN = n;
    };

}, '/entropy_level', recvPort: 57120);
)