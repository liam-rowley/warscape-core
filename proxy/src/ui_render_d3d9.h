#pragma once
// ui_render_d3d9.h - the RmlUi host's render interface (J30), ported from empire-remastered rml_mod/src/rml_render_d3d9.h
// (empire-remastered's shipped interface: layers, filters, clip masks, gradients, box-shadow). Changes from empire-remastered: logging through the proxy
// log, no background image preload (the host decodes on demand), art textures get a full mip chain and trilinear sampling so a 2.5x
// master scales down cleanly (D19), and a missing shader compiler is reported by Ready() == false (the host turns the UI off).
// RmlUi RenderInterface for Direct3D 9, shader-based (vs_3_0 / ps_3_0), with RmlUi 6 advanced rendering:
//   layers (render-to-texture), filters (opacity, blur, drop-shadow, brightness/contrast/... colour matrices, mask-image),
//   clip masks (stencil), gradients (linear/radial/conic, repeating), SaveLayerAsTexture (box-shadow).
// Layer 0 is the game's back buffer, so backdrop-filter samples the game frame. Nested layers, post-process buffers and the
// stencil are D3DPOOL_DEFAULT: released in ReleaseDeviceResources() before IDirect3DDevice9::Reset and recreated lazily.
// Geometry and textures (incl. saved layers) are D3DPOOL_MANAGED and survive Reset.
#include "ui_d3d9.h"
#include <RmlUi/Core/RenderInterface.h>
#include <vector>
#include <unordered_set>
#include <unordered_map>

class RenderInterface_D3D9 : public Rml::RenderInterface {
public:
    explicit RenderInterface_D3D9(IDirect3DDevice9* dev);
    ~RenderInterface_D3D9() override;

    void SetDevice(IDirect3DDevice9* dev) { m_dev = dev; }
    void SetViewport(int w, int h) { m_w = w; m_h = h; }
    void ReleaseDeviceResources();          // before Reset
    bool Ready() const { return m_shadersOk; }
    bool Tried() const { return m_shadersTried; }
    bool EnsureShaders() { if (!m_shadersTried) m_shadersOk = CompileShaders(); return m_shadersOk; }

    void BeginFrame();
    void EndFrame();

    // --- basic ---
    Rml::CompiledGeometryHandle CompileGeometry(Rml::Span<const Rml::Vertex> vertices, Rml::Span<const int> indices) override;
    void RenderGeometry(Rml::CompiledGeometryHandle geometry, Rml::Vector2f translation, Rml::TextureHandle texture) override;
    void ReleaseGeometry(Rml::CompiledGeometryHandle geometry) override;
    Rml::TextureHandle LoadTexture(Rml::Vector2i& texture_dimensions, const Rml::String& source) override;
    Rml::TextureHandle GenerateTexture(Rml::Span<const Rml::byte> source, Rml::Vector2i source_dimensions) override;
    void ReleaseTexture(Rml::TextureHandle texture) override;
    void EnableScissorRegion(bool enable) override;
    void SetScissorRegion(Rml::Rectanglei region) override;
    void SetTransform(const Rml::Matrix4f* transform) override;

    // --- advanced ---
    void EnableClipMask(bool enable) override;
    void RenderToClipMask(Rml::ClipMaskOperation operation, Rml::CompiledGeometryHandle geometry, Rml::Vector2f translation) override;
    Rml::LayerHandle PushLayer() override;
    void CompositeLayers(Rml::LayerHandle source, Rml::LayerHandle destination, Rml::BlendMode blend_mode,
                         Rml::Span<const Rml::CompiledFilterHandle> filters) override;
    void PopLayer() override;
    Rml::TextureHandle SaveLayerAsTexture() override;
    Rml::CompiledFilterHandle SaveLayerAsMaskImage() override;
    Rml::CompiledFilterHandle CompileFilter(const Rml::String& name, const Rml::Dictionary& parameters) override;
    void ReleaseFilter(Rml::CompiledFilterHandle filter) override;
    Rml::CompiledShaderHandle CompileShader(const Rml::String& name, const Rml::Dictionary& parameters) override;
    void RenderShader(Rml::CompiledShaderHandle shader, Rml::CompiledGeometryHandle geometry, Rml::Vector2f translation,
                      Rml::TextureHandle texture) override;
    void ReleaseShader(Rml::CompiledShaderHandle shader) override;

    struct Stats { unsigned draws = 0, geometries = 0, textures = 0, layersPeak = 0, filters = 0; };
    const Stats& GetStats() const { return m_stats; }
    // Per-frame profile (ms spent inside our render interface, by kind). Logged when a frame is slow; see EndFrame.
    struct Prof { double frame = 0, decode = 0, upload = 0, save = 0, rt = 0, geom = 0; unsigned nDecode = 0, nUpload = 0, nSave = 0, nRt = 0, nGeom = 0; };
    const Prof& GetProf() const { return m_prof; }
    static double NowMs();

private:
    struct RT { IDirect3DTexture9* tex = nullptr; IDirect3DSurface9* surf = nullptr; };
    struct Geometry { IDirect3DVertexBuffer9* vb = nullptr; IDirect3DIndexBuffer9* ib = nullptr; UINT numVertices = 0, numIndices = 0; };

    bool CompileShaders();
    bool EnsureTargets();
    bool CreateRT(RT& rt);
    static void FreeRT(RT& rt);
    IDirect3DSurface9* LayerSurface(Rml::LayerHandle layer);
    IDirect3DSurface9* TopSurface() { return LayerSurface((Rml::LayerHandle)(m_layerCount - 1)); }
    void BindTarget(IDirect3DSurface9* s);
    void DrawQuad(IDirect3DTexture9* src, IDirect3DPixelShader9* ps, int vpW, int vpH, Rml::Vector2f uvOffset = {}, Rml::Vector2f uvScale = { 1, 1 });
    void ApplyScissor(Rml::Rectanglei r);
    void RestoreScissor();
    Rml::Rectanglei FilterWindow() const;
    void RenderFilters(Rml::Span<const Rml::CompiledFilterHandle> filters);
    void RenderBlur(float sigma, RT& srcDst, RT& temp, Rml::Rectanglei window);
    void SubmitGeometryTransform(Rml::Vector2f translation);
    Rml::TextureHandle CreateTextureRGBA(const Rml::byte* rgba, int w, int h, bool premultiply, bool mips = false);
    void SetAddress0(DWORD mode);                  // sampler 0 U/V addressing, skips redundant state changes

    IDirect3DDevice9* m_dev;
    int m_w = 0, m_h = 0;
    bool m_shadersOk = false, m_shadersTried = false;

    IDirect3DVertexDeclaration9* m_declMain = nullptr;
    IDirect3DVertexDeclaration9* m_declQuad = nullptr;
    IDirect3DVertexShader9* m_vsMain = nullptr;
    IDirect3DVertexShader9* m_vsQuad = nullptr;
    IDirect3DPixelShader9* m_psColor = nullptr;
    IDirect3DPixelShader9* m_psTexture = nullptr;
    IDirect3DPixelShader9* m_psGradient = nullptr;
    IDirect3DPixelShader9* m_psPassthrough = nullptr;
    IDirect3DPixelShader9* m_psColorMatrix = nullptr;
    IDirect3DPixelShader9* m_psBlendMask = nullptr;
    IDirect3DPixelShader9* m_psBlur = nullptr;
    IDirect3DPixelShader9* m_psDropShadow = nullptr;

    // frame-scoped
    IDirect3DStateBlock9* m_sb = nullptr;
    IDirect3DSurface9* m_savedRT = nullptr;
    IDirect3DSurface9* m_savedDS = nullptr;
    IDirect3DSurface9* m_backBuffer = nullptr;     // layer 0
    // device resources (DEFAULT pool)
    int m_targetW = 0, m_targetH = 0;
    IDirect3DSurface9* m_depthStencil = nullptr;
    std::vector<RT> m_layers;                      // index i = layer handle i (index 0 unused: back buffer)
    RT m_post[3];
    RT m_blendMask;
    int m_layerCount = 0;

    Rml::Matrix4f m_projection, m_transform;
    Rml::Rectanglei m_scissor = Rml::Rectanglei::MakeInvalid();
    bool m_scissorOn = false;
    bool m_clipMaskOn = false;
    DWORD m_stencilRef = 1;
    // Texture addressing: ordinary geometry samples with WRAP so RCSS `repeat` / `repeat-x` / `repeat-y` tile (RmlUi emits
    // texcoords > 1 for them, like the GL3 backend's GL_REPEAT). Post-process quads and SaveLayerAsTexture results (box-shadow)
    // stay CLAMP so blurs and shadow edges do not pull in the opposite edge. m_wrapOk is false on hardware that only allows
    // non-power-of-two textures with CLAMP (D3DPTEXTURECAPS_POW2), where everything stays CLAMP as before.
    bool m_wrapOk = true, m_capsChecked = false;
    DWORD m_addr0 = D3DTADDRESS_CLAMP;
    bool m_mip0 = false;
    std::unordered_set<IDirect3DTexture9*> m_clampTex;
    std::unordered_set<IDirect3DTexture9*> m_mipTex;   // art with a mip chain: sampled trilinear
    Stats m_stats;
    Prof m_prof;
    double m_frameStart = 0;
};
