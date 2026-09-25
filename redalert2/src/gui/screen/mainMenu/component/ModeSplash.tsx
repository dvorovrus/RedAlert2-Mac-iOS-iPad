import React from "react";

interface ModeSplashProps {
    themeId: string;
}

interface Theme {
    eyebrow: string;
    title: string;
    subtitle: string;
    accent: string;
    accent2: string;
    background: string;
}

const THEMES: Record<string, Theme> = {
    yr: {
        eyebrow: "YURI'S REVENGE",
        title: "YURI'S REVENGE",
        subtitle: "Psychic domination protocol active",
        accent: "#d66cff",
        accent2: "#65f1ff",
        background:
            "radial-gradient(circle at 50% 34%, rgba(191,76,255,.42) 0 5%, rgba(49,11,69,.38) 22%, transparent 43%)," +
            "radial-gradient(circle at 18% 72%, rgba(43,221,255,.18), transparent 34%)," +
            "linear-gradient(145deg,#05020a 0%,#16051f 46%,#04070a 100%)",
    },
    "eagle-red": {
        eyebrow: "RED ALERT 2 MOD",
        title: "EAGLE RED",
        subtitle: "Version 1.45 · Total conversion",
        accent: "#ff3a2f",
        accent2: "#ffd46a",
        background:
            "radial-gradient(circle at 68% 36%, rgba(255,48,34,.34), transparent 28%)," +
            "linear-gradient(118deg, transparent 0 33%, rgba(255,57,42,.16) 33% 35%, transparent 35% 50%, rgba(255,196,73,.10) 50% 52%, transparent 52%)," +
            "linear-gradient(145deg,#070303 0%,#260504 52%,#050505 100%)",
    },
    "moomans-rules-ra2": {
        eyebrow: "RED ALERT 2 MOD",
        title: "MOOMAN'S RULES",
        subtitle: "Version 3.0 · RA2 ruleset",
        accent: "#b7d24e",
        accent2: "#f4d85e",
        background:
            "linear-gradient(rgba(185,210,78,.055) 1px,transparent 1px)," +
            "linear-gradient(90deg,rgba(185,210,78,.055) 1px,transparent 1px)," +
            "radial-gradient(circle at 70% 35%, rgba(182,209,73,.24), transparent 30%)," +
            "linear-gradient(145deg,#060704 0%,#18200d 48%,#050505 100%)",
    },
    "moomans-rules-yr": {
        eyebrow: "YURI'S REVENGE MOD",
        title: "MOOMAN'S RULES",
        subtitle: "Version 3.0 · Yuri's Revenge ruleset",
        accent: "#b47cff",
        accent2: "#6ef0d1",
        background:
            "linear-gradient(rgba(180,124,255,.05) 1px,transparent 1px)," +
            "linear-gradient(90deg,rgba(110,240,209,.045) 1px,transparent 1px)," +
            "radial-gradient(circle at 28% 38%, rgba(180,124,255,.30), transparent 30%)," +
            "radial-gradient(circle at 75% 65%, rgba(110,240,209,.16), transparent 30%)," +
            "linear-gradient(145deg,#080510 0%,#191126 52%,#040807 100%)",
    },
    "scorched-earth": {
        eyebrow: "RED ALERT 2 MOD",
        title: "SCORCHED EARTH",
        subtitle: "Smart AI overhaul · Wasteland protocol",
        accent: "#ff8a2a",
        accent2: "#ffd47a",
        background:
            "radial-gradient(circle at 25% 78%, rgba(255,111,25,.34), transparent 26%)," +
            "radial-gradient(circle at 72% 28%, rgba(174,49,16,.30), transparent 30%)," +
            "linear-gradient(160deg,#080604 0%,#2d160b 46%,#090604 100%)",
    },
};

export const ModeSplash: React.FC<ModeSplashProps> = ({ themeId }) => {
    const theme = THEMES[themeId];
    if (!theme) {
        return null;
    }

    const gridSize =
        themeId.startsWith("moomans-rules") ? "34px 34px, 34px 34px, auto, auto" : undefined;

    return (
        <div
            style={{
                position: "relative",
                width: "100%",
                height: "100%",
                overflow: "hidden",
                pointerEvents: "none",
                color: "#fff",
                background: theme.background,
                backgroundSize: gridSize,
                fontFamily: "Arial, Helvetica, sans-serif",
            }}
        >
            <div
                style={{
                    position: "absolute",
                    inset: "-20%",
                    opacity: 0.34,
                    background:
                        "repeating-radial-gradient(circle at 50% 50%, transparent 0 34px, " +
                        theme.accent +
                        " 35px 36px, transparent 37px 69px)",
                    transform: "scale(1.08)",
                }}
            />

            <div
                style={{
                    position: "absolute",
                    left: "8%",
                    top: "9%",
                    padding: "5px 9px",
                    border: "1px solid " + theme.accent + "88",
                    background: "rgba(0,0,0,.56)",
                    color: theme.accent2,
                    fontSize: 11,
                    fontWeight: 800,
                    letterSpacing: ".16em",
                    textTransform: "uppercase",
                }}
            >
                {theme.eyebrow}
            </div>

            <div
                style={{
                    position: "absolute",
                    left: "8%",
                    right: "8%",
                    bottom: "16%",
                    textShadow: "0 3px 12px #000, 0 0 24px " + theme.accent + "55",
                }}
            >
                <div
                    style={{
                        width: 92,
                        height: 4,
                        marginBottom: 14,
                        background: "linear-gradient(90deg," + theme.accent + "," + theme.accent2 + ")",
                        boxShadow: "0 0 12px " + theme.accent,
                    }}
                />
                <div
                    style={{
                        color: "#fff",
                        fontSize: theme.title.length > 15 ? 44 : 50,
                        lineHeight: 0.95,
                        fontWeight: 900,
                        letterSpacing: "-.035em",
                        textTransform: "uppercase",
                    }}
                >
                    {theme.title}
                </div>
                <div
                    style={{
                        marginTop: 11,
                        color: theme.accent2,
                        fontFamily: '"Courier New", monospace',
                        fontSize: 13,
                        fontWeight: 700,
                        letterSpacing: ".06em",
                        textTransform: "uppercase",
                    }}
                >
                    {theme.subtitle}
                </div>
            </div>

            <div
                style={{
                    position: "absolute",
                    inset: 0,
                    boxShadow: "inset 0 0 90px rgba(0,0,0,.88)",
                    background:
                        "repeating-linear-gradient(180deg,rgba(255,255,255,.02) 0 2px,rgba(0,0,0,.035) 2px 4px)",
                }}
            />
        </div>
    );
};
