from pydantic import BaseModel, Field, ConfigDict


class CampoStatus(BaseModel):
    valor: str | None = None
    status: str = "nao_encontrado"  # confirmado, provavel, suspeito, nao_encontrado
    motivo: str | None = None


class Fonte(BaseModel):
    tipo: str = "chunk"  # chunk, tabela, texto
    id: str | None = None
    pagina: int | None = None
    descricao: str | None = None


class Cargo(BaseModel):
    nome: str
    vagas: str | None = None
    remuneracao: str | None = None
    carga_horaria: str | None = None
    requisito: str | None = None
    fonte: str | None = None
    fonte_tipo: str = "chunk"
    pagina: int | None = None
    confianca: str = "media"
    suspeito: bool = False
    motivo_suspeita: str | None = None


class EventoCronograma(BaseModel):
    evento: str
    data_ou_periodo: str
    fonte: str | None = None
    fonte_tipo: str = "chunk"
    pagina: int | None = None
    confianca: str = "media"


class QualidadeIngestao(BaseModel):
    total_chunks: int = 0
    total_tabelas: int = 0
    tipos_chunks: dict[str, int] = Field(default_factory=dict)
    tipos_tabelas: dict[str, int] = Field(default_factory=dict)
    maior_chunk_chars: int = 0
    media_chunk_chars: int = 0
    chunks_muito_pequenos: int = 0
    fontes_texto: int = 0
    fontes_tabela: int = 0
    tabelas_uteis: int = 0
    tabelas_ignoradas: int = 0
    tabelas_continuacao: int = 0
    tabelas_suspeitas: int = 0
    cargos_suspeitos: int = 0
    campos_suspeitos: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)


class ConteudoProgramaticoSecao(BaseModel):
    titulo: str
    topicos: list[str] = Field(default_factory=list)
    pagina: int | None = None
    fonte: str | None = None


class ConcursoResumo(BaseModel):
    model_config = ConfigDict(extra="allow")

    edital_id: str
    titulo: str
    orgao: str | None = None
    banca: str | None = None
    ano: str | None = None
    inscricao: str | None = None
    taxa: str | None = None
    prova: str | None = None
    cargos: list[Cargo] = Field(default_factory=list)
    cronograma: list[EventoCronograma] = Field(default_factory=list)
    campos_nao_encontrados: list[str] = Field(default_factory=list)
    campos_status: dict[str, CampoStatus] = Field(default_factory=dict)
    dados_confirmados: dict[str, str] = Field(default_factory=dict)
    dados_provaveis: dict[str, str] = Field(default_factory=dict)
    dados_suspeitos: dict[str, str] = Field(default_factory=dict)
    qualidade: QualidadeIngestao = Field(default_factory=QualidadeIngestao)
    conteudo_programatico: dict = Field(default_factory=dict)
