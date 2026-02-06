# ANTHROPOCENE
### An immersive audiovisual installation simulating humanity's transformative impact and the progressive erosion of the natural world.

[![Stream Diffusion](https://img.shields.io/badge/Stream_Diffusion-Generative_AI-yellow?logo=huggingface&logoColor=white)](https://github.com/cumulo-autumn/StreamDiffusion)
[![SuperCollider](https://img.shields.io/badge/SuperCollider-Synthesis-red?logo=supercollider&logoColor=black)](https://supercollider.github.io)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-Academic-green)](LICENSE)

![Logo](images_readme/logo.jpg)

## About Us
### Meet Our Team

<table style="width:100%; table-layout:fixed; border-collapse: collapse;">
  <tr>
    <td style="width:25%; vertical-align:top;">
      <div style="text-align:center;">
        <img src="images_readme/Matteo.jpeg" alt="Matteo Di Giovanni" style="width: 100%; max-width: 200px; height: auto; aspect-ratio: 1/1; border-radius: 50%; object-fit: cover;">
        <h4>Matteo Di Giovanni</h4>
        <p>MSc in Music & Acoustic Engineering @POLIMI<br>BSc in Telecommunication Engineering @POLIMI</p>
        <p>
          <a href="mailto:matteo.digiovanni@mail.polimi.it">Mail</a> |
          <a href="https://github.com/matteodigii" target="_blank">GitHub</a> 
          <!--a href="" target="_blank">LinkedIn</a>-->
        </p>
      </div>
    </td>
    <td style="width:25%; vertical-align:top;">
      <div style="text-align:center;">
        <img src="images_readme/Ale.png" alt="Alessandro Mancuso" style="width: 100%; max-width: 200px; height: auto; aspect-ratio: 1/1; border-radius: 50%; object-fit: cover;">
        <h4>Alessandro Mancuso</h4>
        <p>MSc in Music & Acoustic Engineering @POLIMI<br>BSc in Computer Engineering @UniBo</p>
        <p>
          <a href="mailto:alessandro2.mancuso@mail.polimi.it">Mail</a> |
          <a href="https://github.com/AleMancusoPOLI" target="_blank">GitHub</a> 
          <!--a href="" target="_blank">LinkedIn</a>-->
        </p>
      </div>
    </td>
    <td style="width:25%; vertical-align:top;">
      <div style="text-align:center;">
        <img src="images_readme/Filippo.jpg" alt="Filippo Paris" style="width: 100%; max-width: 200px; height: auto; aspect-ratio: 1/1; border-radius: 50%; object-fit: cover;">
        <h4>Filippo Paris</h4>
        <p>MSc in Music & Acoustic Engineering @POLIMI<br>BSc in Computer Engineering @UniBo</p>
        <p>
          <a href="mailto:filippoparis.pro@gmail.com">Mail</a> |
          <a href="https://github.com/fparismusic" target="_blank">GitHub</a> |
          <a href="http://www.linkedin.com/in/filippoparis" target="_blank">LinkedIn</a>
        </p>
      </div>
    </td>
    <td style="width:25%; vertical-align:top;">
      <div style="text-align:center;">
        <img src="images_readme/Ema.jpg" alt="Emanuele Turbanti" style="width: 100%; max-width: 200px; height: auto; aspect-ratio: 1/1; border-radius: 50%; object-fit: cover;">
        <h4>Emanuele Turbanti</h4>
        <p>MSc in Music & Acoustic Engineering @POLIMI<br>BSc in Electrical Engineering @UniBo</p>
        <p>
          <a href="mailto:emanuele.turbanti@mail.polimi.it">Mail</a> |
          <a href="https://github.com/tutututurbo" target="_blank">GitHub</a> 
          <!--a href="" target="_blank">LinkedIn</a>-->
        </p>
      </div>
    </td>
  </tr>
</table>

---

## Table of Contents
01. 📖 [Overview](#-overview)
02. ✨ [The Experience](#-the-experience)
03. 📁 [Project Structure](#-project-structure)  
04. 🚀 [Installation & Setup](#-installation--setup)
05. 🛠️ [Technology Stack](#-technology-stack)
06. 🌍 [Credits & Attributions](#-credits--attributions)
07. 📸 [Visual Preview](#-visual-preview)  
08. 📄 [License & Usage Terms](#-license--usage-terms)

---

## 📖 Overview
**Anthropocene** serves as a bridge between scientific observation and cultural philosophy, manifesting as an interactive audiovisual environment that vividly reconstructs how human presence reshapes the Earth's biosphere. Envisioned as an artistic installation with a generative environment driven by real-time sensors and AI, the project forces a direct confrontation with the reality of how human presence alters and reshapes the natural environment.  

## ✨ The Experience
The user experience begins in a state of pure nature, immersing participants in pristine visuals and sounds, but as camera-based sensors track their movement, the system responds with a progressive metamorphosis: the landscape decays into urban forms and industrial noise, directly reflecting the audience's reshaping influence. This dynamic evolution is designed to foster emotional resonance and intuitive responsibility, inviting viewers to move beyond judgment and engage in deep reflection on their relationship with our world. 

### Phase I: Genesis (Pure Nature)
* **Visuals:** Participants enter an enclosed space immersed in a pristine natural landscape.
* **Audio:** Natural soundscapes—birdsong, wind, flowing water etc.
* **State:** Untouched wilderness.

### Phase II: Colonisation (Progressive Interaction)
* **Trigger:** Sensors detect human presence via computer vision (camera detection).
* **Visuals:** The equilibrium is broken. Vegetation stiffens, and organic branches mutate into geometric shapes and artificial lights.
* **Audio:** Metallic rhythms and distant engines superimpose over the wind.

### Phase III: Saturation (Urban Dominance)
* **Visuals:** The digital city takes complete control. Glitches, frantic traffic, and visual pollution saturate the screens.
* **Audio:** The soundscape collapses into auditory chaos, reflecting acoustic stress.

### Cycle: Rebirth
When the room empties, the structures disintegrate little by little, allowing the forest to slowly regenerate to its initial state.

## 📁 Project Structure

![Map](images_readme/Map.png)

Fully realized architectural vision of Anthropocene. While the project can be scaled down for smaller demonstrations, this layout represents the optimal deployment designed for a dedicated exhibition space with sufficient resources.

* **Central Console:** The "brain" of the operation (Laptop/Workstation), managing the OSC communication pipeline between vision, audio, and sensing logic.

* **Immersive Visual:** A large-scale generative screen (or projection) dominates the scene, driven by TouchDesigner and Stream Diffusion.

* **Spatial Audio Field:** Two active speakers (Stereo) are positioned flanking the screen. Controlled by SuperCollider, they create a stereo field that physically envelops the audience.

* **Interactive Zone:** A centralized area where the audience is tracked. A standalone camera, positioned towards the crowd, feeds real-time data to the Python/YOLO controller to trigger state changes based on crowd density.

* **Atmospheric Lighting:** A grid of DMX-controlled LED spots on the ceiling (or on the ground) reacts to the system's "entropy level".

## 🚀 Installation & Setup

### Hardware Requirements
* **Projector:** For immersive visual output.
* **Camera:** For presence detection (webcam or USB camera).
* **Speakers:** For spatial audio experience.
* **Computing Power:**
  * **Internet connection:** Required for remote Stream Diffusion inference.
  * **OR High-end GPU:** (e.g., NVIDIA RTX 3080 or higher) to run the model locally without an internet connection.

### Running the Project
1.  **Audio:** Boot the **SuperCollider** server and load the `main.scd` file to start the audio engine.
2.  **Sensing:** Run the **Python** controller to start the computer vision system:
    ```bash
    pip install ultralytics python-osc
    python detection_controller.py
    ```
3.  **Visuals:** Open `Anthropocene.toe` in **TouchDesigner**. Ensure the OSC in/out ports match the Python configuration.


## 🛠️ Technology Stack

The system relies on a distributed architecture to handle real-time generative media.

### Visual System
* **TouchDesigner:** Handles dynamic environmental rendering, fluid state transitions, and responsive visual morphing.
* **Stream Diffusion (Remote):** Utilized for high-fidelity generative landscapes. Due to high computational costs, models are run on remote servers.
* **DayDream:** A lightweight visual framework used for post-processing effects and ambient textures that bridge the gap between generative AI and real-time rendering.

### Audio Engine
* **SuperCollider:** Generates adaptive soundscapes using procedural sound design and granular synthesis.
* **Reaper:** Acts as the primary Digital Audio Workstation for music composition.

### Interaction & Sensing
* **YOLO (Ultralytics):** Camera-based presence detection and multi-participant tracking.
* **Python:** A communication pipeline that normalizes tracking data and controls system parameters in real-time.
* **OSC:** The low-latency network protocol used to synchronize data between Python, SuperCollider, and TouchDesigner.
* **DMX:** Controls the physical lighting environment.

### Key Packages
```yaml
dependencies:
  # Phyton
  python: 3.x
  pyhtonosc
  numpy
  time
  cv2

  # YOLO ultralytics models
  yolo11n.pt
  yolov8n-seg.pt

  # TouchDesigner
  DayDream API
```

## 🌍 Credits & Attributions

This project was conceived and developed as part of the **Creative Programming and Computing** course (A.Y. 2025/2026) at **Politecnico di Milano**.

**Core Frameworks & Libraries**
* **Generative Visuals:** [Stream Diffusion](https://github.com/cumulo-autumn/StreamDiffusion) pipeline & [TouchDesigner](https://derivative.ca/).
* **Audio Engine:** [SuperCollider](https://supercollider.github.io/) (Real-time synthesis) & [Reaper](https://www.reaper.fm/) (Composition).
* **Sensing & Logic:** [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) for computer vision & `python-osc` for networking.

**Acknowledgements**
* Special thanks to the open-source community for the **DayDream** visual framework.
* Models hosted and accelerated via **HuggingFace**.
  
## 📸 Visual Preview

---

## 📄 License & Usage Terms
**ANTHROPOCENE © 2026 All Rights Reserved.** 

No part of this project may be reproduced or used for commercial purposes without explicit permission from the authors.
