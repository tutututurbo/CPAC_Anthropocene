Server.killAll;
s.reboot;
(
// --- SETUP ---
OSCdef.freeAll;
Window.closeAll;

s.options.sampleRate = 48000;
s.options.hardwareBufferSize = 1024;
s.options.memSize = 65536;

s.waitForBoot({

    // --- PREPARAZIONE ---
    s.freeAll;
    Buffer.freeAll;
    s.sync;

	~busDry = Bus.audio(s, 2);

    // Buffer Audio

	~soundPath = PathName(thisProcess.nowExecutingPath).parentPath ++ "Layers/";
    ~files = ["1.mp3", "2.mp3", "3.mp3", "4.mp3", "5.mp3", "6.mp3"];
	// Safety check
    if(File.exists(~soundPath).not) { "⚠️ CARTELlA 'Layers' NON TROVATA!".warn };
    ~buffers = ~files.collect { |f| Buffer.read(s, ~soundPath ++ f); };

    // Buffer Oscilloscopio
    ~scopeBuf = Buffer.alloc(s, 1024, 2);

    s.sync;
    "Buffer Audio Caricati.".postln;

    // --- SYNTHS ---
    NetAddr("127.0.0.1", 57120);
    ~lastN = 0;

    SynthDef(\texturePlayer, {
        |buf, amp = 0, grainMix = 0, cleanLevel = 1,
        dens = 1, grainDur = 2, panSpread = 0, jitter = 0,
		timeStretch = 1.0, // 1 = normale, 0.5 = metà velocità
        pitchJitter = 0.0, // 0 = intonato, 0.1 = stonato
		out = 0|

        var cleanSig, grainSig, finalSig;
        var grainTrig, grainPos, pan, warpedRate;

		// Rallenta e oscilla, ma SOLO per la texture granulare
        // Base rate (timeStretch) * Oscillazione lenta (Jitter)
        // LFNoise1 crea un movimento fluido del pitch
        warpedRate = timeStretch.lag(4.0) * LFNoise1.kr(0.2).range(1 - pitchJitter, 1 + pitchJitter);

        // Clean
        cleanSig = PlayBuf.ar(2, buf, BufRateScale.kr(buf), loop: 1);
        cleanSig = cleanSig * cleanLevel.lag(2.0);

        // Granulator "CLOUDY"
        // Densità molto più bassa (lenta) perché i grani sono lunghi
        grainTrig = Impulse.kr(dens.lag(5.0));

        // La posizione di lettura rallenta col timeStretch, ma il pitch è gestito da warpedRate
        grainPos = LFNoise1.kr(0.05 * timeStretch).range(0, 1) + (LFNoise0.kr(dens) * jitter);
        grainPos = grainPos.clip(0, 1);
        pan = TRand.kr(panSpread.neg, panSpread, grainTrig);

        // Interpolazione 4 (Cubica) per evitare artefatti
        grainSig = GrainBuf.ar(2, grainTrig, grainDur.lag(2.0), buf, warpedRate, grainPos, 4, pan);

        // Filtro sui grani: se rallentano, diventano più scuri e lontani
        grainSig = LPF.ar(grainSig, timeStretch.linlin(0.7, 1, 4000, 16000));

        // Gain reduction: con grani lunghi la sovrapposizione aumenta il volume
        grainSig = grainSig * 0.5;

        // Mix
        finalSig = cleanSig + (grainSig * grainMix.lag(3.0)); // Lag più lungo per mix sognante
        finalSig = finalSig * Lag.kr(amp, 1.5);
        finalSig = finalSig.tanh;

        Out.ar(out, finalSig);
    }).add;

	SynthDef(\masterFX, {
        |inBus, out = 0, revMix = 0.3, roomSize = 0.5|
        var input, wet, sig;

        input = In.ar(inBus, 2);

        // LEAK DC: Rimuove frequenze "invisibili" che causano rumore nel riverbero
        input = LeakDC.ar(input);

        // FREEVERB2: Molto più pulito e "Lush" del GVerb
        // roomSize qui va da 0 a 1 (lo mappiamo dopo)
        wet = FreeVerb2.ar(
            input[0], input[1], // Input Stereo Reale
            mix: 1, // Sempre 100% wet qui, mixiamo dopo
            room: roomSize.clip(0, 1),
            damp: 0.4 // Assorbimento alte frequenze
        );

        // Mix Dry/Wet
        sig = XFade2.ar(input, wet, revMix.linlin(0, 1, -1, 1));

		//sig = LPF.ar(sig, 16000);

        // Limiter finale
        sig = Limiter.ar(sig, 0.95, 0.01);

        ScopeOut2.ar(sig, ~scopeBuf);
        Out.ar(out, sig);
    }).add;

    s.sync;

    // --- GUI ---
    {
        var w = Window("ENTROPY ENGINE", Rect(100, 100, 700, 480)).front.alwaysOnTop_(true);
        w.background_(Color(0.1, 0.1, 0.12)); // Dark Theme

        ~bigFont = Font("Helvetica", 90, true);

        // Label Titolo
        StaticText(w, Rect(20, 20, 200, 30)).string_("ENTROPY INDEX").stringColor_(Color.gray(0.8));

        // Display Numero Gigante
        ~numDisp = StaticText(w, Rect(20, 60, 150, 100))
            .string_("0")
            .font_(~bigFont)
            .stringColor_(Color.white)
            .align_(\center);

        // Meter Clean
        StaticText(w, Rect(200, 20, 100, 20)).string_("CLEAN").stringColor_(Color.white);
        ~barClean = LevelIndicator(w, Rect(200, 50, 30, 200))
            .warning_(0.6).critical_(0.9)
            .style_(\continuous)
            .background_(Color.black);

        // Meter Grain
        StaticText(w, Rect(260, 20, 100, 20)).string_("GRAIN").stringColor_(Color.white);
        ~barGrain = LevelIndicator(w, Rect(260, 50, 30, 200))
            .warning_(0.6).critical_(0.9)
            .style_(\continuous)
            .background_(Color.black);

        // Layer LEDs
        StaticText(w, Rect(320, 20, 200, 20)).string_("ACTIVE LAYERS").stringColor_(Color.white);
        ~layerLeds = 6.collect { |i|
            LevelIndicator(w, Rect(320 + (i*40), 50, 30, 150))
                .style_(\led) // Stile LED
                .stepWidth_(5) // Spazio tra i led
                .numSteps_(15) // Numero di segmenti
                .background_(Color.black);
        };

        // Oscilloscopio
        StaticText(w, Rect(20, 270, 200, 20)).string_("VISUALIZER").stringColor_(Color.gray(0.5));
        ~scope = ScopeView(w, Rect(20, 290, 660, 150));
        ~scope.bufnum = ~scopeBuf.bufnum;
        ~scope.server = s;
        ~scope.style = 1;
        ~scope.waveColors = [Color.new255(0, 255, 255), Color.new255(255, 0, 255)]; // Neon
        ~scope.background = Color.black;
        ~scope.start;

        w.onClose = { s.freeAll; OSCdef.freeAll; };
    }.defer;
    s.sync;

    // --- AVVIO MOTORE ---
	~grpSource = Group.new;
    ~grpFX = Group.after(~grpSource);

    ~layers = ~buffers.collect { |buf|
        Synth(\texturePlayer, [
            \buf, buf,
            \out, ~busDry,
            \amp, 0,
            \grainMix, 0.1
        ], target: ~grpSource);
    };

    // Il MasterFX legge dal bus interno e va alle casse (0), nel gruppo FX
    ~master = Synth(\masterFX, [ \inBus, ~busDry, \out, 0 ], target: ~grpFX);

    s.sync;

    // --- LOGICA AGGIORNATA ---
    ~updateLayers = { |n|
        var chaos, cleanVol, density, spread, duration, jitter;
		var revMix, revSize;
		var timeStretch, pitchJitter;

        var grainMap = [0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9];

        n = n.clip(0, ~layers.size);

        // 1. Chaos Mix
        if (n > 0) { chaos = grainMap[n]; } { chaos = 0; };

        // 2. Clean Volume
        if (n <= 3) {
            cleanVol = 1.0;
        } {
            if (n == 4) { cleanVol = 0.8; };
            if (n == 5) { cleanVol = 0.7; };
            if (n == 6) { cleanVol = 0.65; };
        };

        // NUOVI PARAMETRI "ATMOSFERICI"
        // Densità: da 0.5Hz (uno ogni 2 sec) a 4Hz (4 al secondo)
        density = n.linlin(1, 6, 0.5, 4);

        // Durata: da 3 secondi a 1.5 secondi
        // Più sale il livello, più i grani si accorciano un po' per diventare più "fitti",
        // ma partiamo da suoni lunghissimi e morbidi.
        duration = n.linlin(1, 6, 3.0, 1.5);

        jitter = n.linlin(1, 6, 0.001, 0.1); // Jitter aumenta per non rendere il loop noioso
        spread = n.linlin(1, 6, 0.3, 1.0);

		revMix = n.linlin(0, 6, 0.2, 0.5); // Da 20% a 50% wet
        revSize = n.linlin(0, 6, 0.4, 0.8); // Da stanza piccola a grande

		// Time Stretch: A lvl 0 è 1.0 (normale). A lvl 6 è 0.5 (DIMEZZATO / Ottava Sotto)
        timeStretch = n.linlin(0, 6, 1.0, 0.8);

        // Pitch Jitter: A lvl 0-2 è fermo. Da lvl 3 in poi inizia a stonare.
        if(n > 2) {
             pitchJitter = n.linlin(2, 6, 0.0, 0.03);
        } {
             pitchJitter = 0;
        };

        // GUI
        {
            ~numDisp.string_(n.asInteger.asString);

            if(n >= 4) {
                ~numDisp.stringColor_(Color.new255(255, 50, 50)); // Rosso acceso
            } {
                ~numDisp.stringColor_(Color.white); // Bianco normale
            };

            ~barClean.value_(cleanVol);
            ~barGrain.value_(chaos);
        }.defer;

        // DEBUG
        ("Lvl: " ++ n ++ " | Dur: " ++ duration.round(0.1) ++ "s | Dens: " ++ density.round(0.1) ++ "Hz").postln;
		("      " ++ " | Speed: " ++ timeStretch.round(0.1) ++ "x | Detune: " ++ pitchJitter.round(0.01)).postln;

		// Synth
        ~layers.do { |synth, i|
            var distance, amp;
            if (i < n) {
                distance = (n - 1) - i;
                amp = 1 / (distance + 1);
            } {
                amp = 0;
            };
            { ~layerLeds[i].value_(amp); }.defer;

            synth.set(
                \amp, amp, \grainMix, chaos, \cleanLevel, cleanVol,
                \dens, density, \grainDur, duration, \panSpread, spread, \jitter, jitter,
				\timeStretch, timeStretch,
                \pitchJitter, pitchJitter
            );
        };

		~master.set(\revMix, revMix, \roomSize, revSize);
    };

    // --- OSC ---
    ("--- ASCOLTO SULLA PORTA: " ++ NetAddr.langPort ++ " ---").postln;

    OSCdef(\mainCtrl, { |msg|
        var n = msg[1].asInteger;
        if (n != ~lastN) {
            { ~updateLayers.(n); }.defer;
            ~lastN = n;
        };
    }, '/entropy_level', recvPort: 57120);

    "--- SISTEMA CLOUD PRONTO ---".postln;
});
)