# ANTHROPOCENE
### An Immersive Audiovisual Simulation of Human Impact on Nature

**Creative Programming and Computing 2025/26 - Politecnico di Milano**

*Matteo Di Giovanni · Alessandro Mancuso · Filippo Paris · Emanuele Turbanti*

## Table of Contents
1. 📖 [Overview](#overview)  
2. 🎮 [The Experience](#the-experience)  
3. 🚀 [Installation & Setup](#installation--setup)  
4. 🛠️ [Technology Stack](#technology-stack) 
5. 📸 [Visual Preview](#visual-preview)  
6. 📄 [License & Usage Terms](#license--usage-terms)

---

## 📖 Overview
**Anthropocene** is an immersive audiovisual installation acting as an "algorithmic mirror". It defines our current era by acknowledging humanity as the primary driver of planetary-scale environmental transformation.

The project bridges science and philosophy, translating abstract concepts into a visceral, embodied experience. Starting from a pristine natural landscape, the environment evolves—or devolves—in real-time based on audience presence, inviting reflection on our relationship with the ecosystem rather than assigning blame.


## 🎮 The Experience
The installation simulates a living digital forest that responds to the "anthropic level" of the room.

### Phase I: Genesis (Pure Nature)
* **Visuals:** Participants enter an enclosed space immersed in a pristine landscape. [cite_start]Organic visuals dance across surfaces.
* **Audio:** Natural soundscapes—birdsong, wind, flowing water.
* **State:** Untouched wilderness.

### Phase II: Colonisation (Progressive Interaction)
* **Trigger:** Sensors detect human presence via computer vision.
* **Metamorphosis:** The equilibrium is broken. Vegetation stiffens, and organic branches mutate into geometric shapes and artificial lights.
* **Audio:** Metallic rhythms and distant engines superimpose over the wind.

### Phase III: Saturation (Urban Dominance)
* **Trigger:** A critical threshold of visitors is surpassed.
* **Visuals:** The digital city takes complete control. Glitches, frantic traffic, and visual pollution saturate the screens.
* **Audio:** The soundscape collapses into auditory chaos, reflecting acoustic stress.

### Cycle: Collapse or Rebirth
When the room empties, the structures disintegrate, allowing the forest to slowly regenerate to its initial state.


## 🚀 Installation & Setup

### Hardware Requirements
* **Projector:** For immersive visual output.
* **Camera:** For presence detection (webcam or USB camera).
* **Speakers:** For spatial audio experience.
* **Internet Connection:** Required for remote Stream Diffusion inference.

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

### Audio Engine
* **SuperCollider:** Generates adaptive soundscapes using procedural sound design and granular synthesis.
* **Context-Aware:** Audio layers evolve seamlessly from organic to industrial based on system state.

### Interaction & Sensing
* **YOLO (Ultralytics):** Camera-based presence detection and multi-participant tracking.
* **Python & OSC:** A communication pipeline that normalizes tracking data and controls system parameters in real-time.


## Visual Preview


## 📄 License & Usage Terms
**ANTHROPOCENE © 2026 All Rights Reserved.** 

This project is an academic work developed for the "Creative Programming and Computing" course at Politecnico di Milano. No part of this project may be reproduced or used for commercial purposes without explicit permission from the authors.
