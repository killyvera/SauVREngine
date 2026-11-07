// Culling por software: oclusores (paredes y suelos grandes) rasterizados en CPU en un buffer de
// profundidad pequeño; un VA lejano se descarta si su caja queda detrás de los oclusores en toda
// su zona de pantalla. No usa consultas GL, así que no toca el driver de la GPU.
// Se incluye desde renderva.cpp, antes de rendergeom (usa visibleva, camera1, camprojmatrix, insideva).
//
// Conservador en todo: un VA solo se descarta si queda oculto en cada vista (los dos ojos con
// multiview), el oclusor solo cubre los píxeles que tapa enteros y con su profundidad más lejana
// dentro del píxel, y una caja que cruza el plano cercano cuenta como visible.

// Apagado: en ruebli no descarta casi nada (VAs grandes, el PVS ya quita lo oculto) y cuesta ~2,5 ms de CPU.
// VAR y no VARP para que no se guarde en la config del visor; se llama distinto del antiguo VARP
// swocclude para que un "swocclude 1" guardado no lo vuelva a encender.
VAR(swoccludetest, 0, 0, 1);
VAR(swoccludedist, 0, 128, 4096);
VAR(swoccludebudget, 0, 4000, 100000);
int swcull = 0, swus = 0;
// Diagnóstico: 0 triangulos oclusores rasterizados, 1 zonas probadas, 2 no descartadas por cruzar el plano cercano, 3 no descartadas por profundidad, 4 triangulos oclusores de las zonas visibles.
int swdiag[5] = { 0, 0, 0, 0, 0 };
static const int swow = 128, swoh = 96, swmaxviews = 2;
static float swdepth[swmaxviews][swow*swoh];
static int swviews = 1, swframe = 0;
static bool swactive = false;
static matrix4 swmat[swmaxviews];

static inline vec4 swclip(const matrix4 &m, const vec &p)
{
    return vec4(m.a.x*p.x + m.b.x*p.y + m.c.x*p.z + m.d.x,
                m.a.y*p.x + m.b.y*p.y + m.c.y*p.z + m.d.y,
                m.a.z*p.x + m.b.z*p.y + m.c.z*p.z + m.d.z,
                m.a.w*p.x + m.b.w*p.y + m.c.w*p.z + m.d.w);
}

// Distancia al plano cercano de GL (z = -w): >= 0 delante de la cámara.
static inline float swneardist(const vec4 &c) { return c.z + c.w; }

static inline vec swscreen(const vec4 &c)
{
    float iw = 1.0f/c.w;
    return vec((c.x*iw*0.5f + 0.5f)*swow, (c.y*iw*0.5f + 0.5f)*swoh, c.z*iw);
}

// Marca solo los píxeles que el triángulo cubre enteros (las 4 esquinas dentro) y guarda la
// profundidad más lejana del triángulo dentro del píxel. Barycentricas y z son afines en pantalla,
// así que el mínimo y el máximo sobre el píxel salen de los coeficientes sin evaluar las esquinas.
static void swtri(float *depth, const vec &p0, const vec &p1, const vec &p2)
{
    float area = (p1.x-p0.x)*(p2.y-p0.y) - (p1.y-p0.y)*(p2.x-p0.x);
    if(fabsf(area) < 1e-6f) return;
    float inv = 1.0f/area;
    float a0 = (p1.y-p2.y)*inv, b0 = (p2.x-p1.x)*inv, c0 = (p1.x*p2.y - p1.y*p2.x)*inv;
    float a1 = (p2.y-p0.y)*inv, b1 = (p0.x-p2.x)*inv, c1 = (p2.x*p0.y - p2.y*p0.x)*inv;
    float a2 = -a0-a1, b2 = -b0-b1, c2 = 1 - c0 - c1;
    float az = a0*(p0.z-p2.z) + a1*(p1.z-p2.z), bz = b0*(p0.z-p2.z) + b1*(p1.z-p2.z), cz = p2.z + c0*(p0.z-p2.z) + c1*(p1.z-p2.z);
    float m0 = min(a0, 0.0f) + min(b0, 0.0f), m1 = min(a1, 0.0f) + min(b1, 0.0f), m2 = min(a2, 0.0f) + min(b2, 0.0f);
    float mz = max(az, 0.0f) + max(bz, 0.0f);
    int minx = max(0, int(floorf(min(p0.x, min(p1.x, p2.x)))));
    int maxx = min(swow-1, int(ceilf(max(p0.x, max(p1.x, p2.x)))));
    int miny = max(0, int(floorf(min(p0.y, min(p1.y, p2.y)))));
    int maxy = min(swoh-1, int(ceilf(max(p0.y, max(p1.y, p2.y)))));
    for(int py = miny; py <= maxy; py++) for(int px = minx; px <= maxx; px++)
    {
        // Valores en la esquina (px, py); el mínimo sobre el píxel suma la parte negativa de cada pendiente.
        if(a0*px + b0*py + c0 + m0 < 0 || a1*px + b1*py + c1 + m1 < 0 || a2*px + b2*py + c2 + m2 < 0) continue;
        float z = az*px + bz*py + cz + mz;
        float &d = depth[py*swow + px];
        if(z < d) d = z;
    }
}

// Recorta el triángulo contra el plano cercano (hasta 4 vértices) y lo rasteriza en abanico.
static void swoccluder(int view, const vec &v0, const vec &v1, const vec &v2)
{
    const matrix4 &m = swmat[view];
    vec4 in[3] = { swclip(m, v0), swclip(m, v1), swclip(m, v2) }, out[4];
    int n = 0;
    loopi(3)
    {
        const vec4 &a = in[i], &b = in[(i+1)%3];
        float da = swneardist(a), db = swneardist(b);
        if(da >= 0) out[n++] = a;
        if((da >= 0) != (db >= 0)) out[n++] = vec4(a).lerp(b, da/(da - db));
    }
    if(n < 3) return;
    vec s[4];
    loopi(n)
    {
        if(out[i].w < 1e-5f) return;
        s[i] = swscreen(out[i]);
    }
    for(int i = 1; i + 1 < n; i++) swtri(swdepth[view], s[0], s[i], s[i+1]);
    swdiag[0]++;
}

static bool swoccludedview(int view, const vec &mn, const vec &mx)
{
    const matrix4 &m = swmat[view];
    float minx = 1e9f, miny = 1e9f, minz = 1e9f, maxx = -1e9f, maxy = -1e9f;
    loopi(8)
    {
        vec4 c = swclip(m, vec(i&1 ? mx.x : mn.x, i&2 ? mx.y : mn.y, i&4 ? mx.z : mn.z));
        if(swneardist(c) < 0 || c.w < 1e-5f) { swdiag[2]++; return false; }
        vec s = swscreen(c);
        minx = min(minx, s.x); maxx = max(maxx, s.x);
        miny = min(miny, s.y); maxy = max(maxy, s.y);
        minz = min(minz, s.z);
    }
    int x0 = max(0, int(floorf(minx)) - 1), x1 = min(swow-1, int(ceilf(maxx)) + 1);
    int y0 = max(0, int(floorf(miny)) - 1), y1 = min(swoh-1, int(ceilf(maxy)) + 1);
    // Fuera de esta vista: no se ve en ella, así que no impide descartarla.
    if(x0 > x1 || y0 > y1) return true;
    const float *depth = swdepth[view];
    for(int py = y0; py <= y1; py++) for(int px = x0; px <= x1; px++)
    {
        if(depth[py*swow + px] >= minz - 0.002f) { swdiag[3]++; return false; }
    }
    return true;
}

static bool swoccluded(vtxarray *va)
{
    swdiag[1]++;
    vec mn(float(va->bbmin.x), float(va->bbmin.y), float(va->bbmin.z));
    vec mx(float(va->bbmax.x), float(va->bbmax.y), float(va->bbmax.z));
    loopi(swviews) if(!swoccludedview(i, mn, mx)) return false;
    return true;
}

static inline bool swisculled(vtxarray *va) { return va->swframe == swframe; }

static void swbuild()
{
    Uint64 t0 = SDL_GetPerformanceCounter();
    swframe++;
    swcull = 0;
    loopi(5) swdiag[i] = 0;
#ifdef __ANDROID__
    // Con multiview un solo pase dibuja los dos ojos: hay que probar cada ojo, no la cámara central.
    extern int vrmultiviewactive;
    if(vrmultiviewactive) { geteyecamprojs(swmat); swviews = 2; }
    else
#endif
    { swmat[0] = camprojmatrix; swviews = 1; }
    loopi(swviews) loopj(swow*swoh) swdepth[i][j] = 2.0f;
    int budget = swoccludebudget;
    for(vtxarray *va = visibleva; va && budget > 0; va = va->next)
    {
        if(insideva(va, camera1->o)) continue;
        for(int i = 0; i + 8 < va->occ.length() && budget > 0; i += 9, budget--)
        {
            const float *o = &va->occ[i];
            vec v0(o[0], o[1], o[2]), v1(o[3], o[4], o[5]), v2(o[6], o[7], o[8]);
            loopj(swviews) swoccluder(j, v0, v1, v2);
        }
    }
    for(vtxarray *va = visibleva; va; va = va->next) swdiag[4] += va->occ.length()/9;
    for(vtxarray *va = visibleva; va; va = va->next)
    {
        if(va->distance <= swoccludedist || insideva(va, camera1->o)) continue;
        if(swoccluded(va)) { va->swframe = swframe; swcull++; }
    }
    swus = int((SDL_GetPerformanceCounter() - t0) * 1000000 / SDL_GetPerformanceFrequency());
}
