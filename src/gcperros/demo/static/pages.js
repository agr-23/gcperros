// El selector de deporte también en «Por qué confiar» y «Bajo el capó»: cada
// enlace abre «En vivo» con su partido. Los partidos los dice el servidor, como
// en app.js, así que no hay identificadores escritos a mano que se desfasen.
(async () => {
  const nav = document.getElementById("sports");
  if (!nav) return;
  try {
    const response = await fetch("/api/sports");
    if (!response.ok) return;
    const sports = await response.json();
    nav.replaceChildren(
      ...sports.map(({ match_id: matchId, sport }) => {
        const config = SPORTS[sport] ?? SPORTS.football;
        const link = document.createElement("a");
        link.href = `/?partido=${encodeURIComponent(matchId)}`;
        const icon = document.createElement("span");
        icon.className = "sport-ball";
        icon.textContent = config.icon;
        const label = document.createElement("span");
        label.className = "sport-label";
        label.textContent = config.label;
        link.append(icon, label);
        return link;
      }),
    );
    nav.hidden = sports.length < 2;
  } catch {
    // Sin servidor no hay partido al que ir: el selector no aparece.
  }
})();
