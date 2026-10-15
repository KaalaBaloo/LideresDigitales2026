import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api.js";
import Home from "./pages/Home.jsx";
import Opportunity from "./pages/Opportunity.jsx";
import Alerts from "./pages/Alerts.jsx";
import Profile from "./pages/Profile.jsx";
import Learnings from "./pages/Learnings.jsx";
import SensorDemo from "./pages/SensorDemo.jsx";

const ShopCtx = createContext(null);
export const useShop = () => useContext(ShopCtx);

export default function App() {
  const [shops, setShops] = useState([]);
  const [shopId, setShopId] = useState(() => Number(localStorage.getItem("shopId")) || null);
  const [shop, setShop] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .shops()
      .then((s) => {
        setShops(s);
        if (!s.find((x) => x.id === shopId)) setShopId((s.find((x) => x.role === "main") || s[0])?.id ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!shopId) return;
    try {
      localStorage.setItem("shopId", String(shopId));
    } catch {}
    api.shop(shopId).then(setShop).catch((e) => setError(e.message));
  }, [shopId]);

  const reloadShop = () => api.shop(shopId).then(setShop);

  return (
    <ShopCtx.Provider value={{ shop, shopId, reloadShop }}>
      <div className="app">
        <header className="top">
          <div className="brand">
            <span className="logo">↗</span> atravia
          </div>
          <select value={shopId ?? ""} onChange={(e) => setShopId(Number(e.target.value))} aria-label="Comercio">
            {shops.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {s.role === "main" ? "calle principal" : "calle lateral"}
              </option>
            ))}
          </select>
        </header>
        <div className="demo">
          DEMO · Comercio y cámara simulados (synthetic) · Datos de ciudad reales de datos.madrid.es
        </div>
        <nav className="tabs">
          <NavLink to="/" end>Inicio</NavLink>
          <NavLink to="/alertas">Alertas</NavLink>
          <NavLink to="/aprendizajes">Aprendizajes</NavLink>
          <NavLink to="/perfil">Perfil</NavLink>
          <NavLink to="/sensor">Sensor</NavLink>
        </nav>
        <main>
          {error && <p className="error">No se pudo conectar con la API: {error}</p>}
          {!shop && !error && <p className="muted">Cargando…</p>}
          {shop && (
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/oportunidad/:date/:hour" element={<Opportunity />} />
              <Route path="/alertas" element={<Alerts />} />
              <Route path="/aprendizajes" element={<Learnings />} />
              <Route path="/perfil" element={<Profile />} />
              <Route path="/sensor" element={<SensorDemo />} />
            </Routes>
          )}
        </main>
      </div>
    </ShopCtx.Provider>
  );
}
