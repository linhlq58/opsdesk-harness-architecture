# Python cheat sheet cho người đọc code harness

Mục tiêu: đọc được code OpsDesk ở mức **từng khối** ("khối này làm gì, vì sao"), không cần tự viết từng dòng.
Mỗi mẫu có: nhận diện thế nào, nghĩa là gì, so với Kotlin, và ví dụ lấy từ chính repo.

---

## 1. Type hint: "biến này có kiểu gì"

```python
async def get(self, tenant_id: TenantId, ticket_id: TicketId) -> Ticket | None: ...
```
- `tên: Kiểu` cho tham số, `-> Kiểu` cho giá trị trả về.
- `Ticket | None` = có thể là `Ticket` hoặc `None` (Kotlin: `Ticket?`).
- `list[Ticket]`, `dict[str, int]`, `frozenset[Role]`, `tuple[str, ...]` (tuple dài tùy ý).
- Python **không** kiểm tra kiểu lúc chạy; pyright kiểm tra khi bạn gõ code / trên CI.

**Đọc nhanh:** bỏ qua phần sau dấu `:` và `->` nếu chỉ cần biết luồng chạy.

## 2. `async` / `await`: "hàm có chờ I/O"

```python
async def publish(self, event: Event) -> None:
    for sink in self._sinks:
        await sink.handle(event)
```
- `async def` = hàm bất đồng bộ (Kotlin: `suspend fun`).
- `await x` = chờ `x` xong mà không chặn cả chương trình (Kotlin: gọi một `suspend fun`).
- Gặp `async`/`await` → nghĩa là ở đó có I/O: DB, mạng, model, file.

## 3. Context manager `with` / `async with`: "mở rồi chắc chắn đóng"

```python
async with open_sqlite_repositories(Path("var/opsdesk.db")) as repos:
    await repos.tickets.save(ticket)
```
- Mở tài nguyên, dùng trong khối thụt lề, **tự đóng** khi ra khỏi khối, kể cả khi có lỗi.
- Kotlin: `use { }`. Trên Windows rất quan trọng: quên đóng file/DB là file bị khóa.

## 4. Pydantic model: "dữ liệu có kiểm tra"

```python
class Principal(BaseModel, frozen=True, extra="forbid"):
    tenant_id: TenantId
    roles: frozenset[Role]
    scopes: frozenset[Scope]

    @model_validator(mode="after")
    def _derived_fields_match_roles(self) -> Self:
        if self.scopes != scopes_for(self.roles):
            raise ValueError("scopes must be derived from roles")
        return self
```
- Khai báo field như data class; **pydantic kiểm tra và chuyển kiểu lúc tạo** (khác Python thường).
- `frozen=True` = bất biến. `extra="forbid"` = có field lạ thì báo lỗi.
- `@model_validator` / `@field_validator` = luật kiểm tra thêm (invariant).
- `.model_dump()` → dict, `.model_dump_json()` → chuỗi JSON, `Model.model_validate(dict)` → tạo từ dict.
- Kotlin gần nhất: `@Serializable data class` + `init { require(...) }`.

**Dùng ở đâu:** mọi dữ liệu đi qua ranh giới (tool args, API, event, seed YAML).

## 5. `@dataclass`: "data class nhẹ, không kiểm tra"

```python
@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: ReasonCode

    def __post_init__(self) -> None:
        if self.allowed != (self.reason is ReasonCode.OK):
            raise ValueError("inconsistent decision")
```
- Như `data class` Kotlin: tự sinh `__init__`, `__eq__`, `__repr__`.
- `frozen=True` = `val`, `slots=True` = gọn bộ nhớ (bỏ qua khi đọc).
- `__post_init__` = khối `init {}` chạy sau khi tạo.
- Khác pydantic: **không** tự kiểm tra kiểu. Dùng cho giá trị nội bộ (`Decision`, `Money`, `ToolContext`).

## 6. `Protocol`: "interface"

```python
class EventSink(Protocol):
    @property
    def name(self) -> str: ...
    async def handle(self, event: Event) -> None: ...
```
- Kotlin: `interface`. `...` = thân hàm để trống.
- Khác Kotlin: class **không cần** khai báo `implements`. Có đủ method đúng chữ ký là "khớp" (structural typing).
- Gặp `Protocol` → đây là **port** hoặc hợp đồng; tìm các class cài đặt nó (adapter).

## 7. `StrEnum`: "enum mà giá trị là chuỗi"

```python
class Scope(StrEnum):
    TICKET_READ = "ticket:read"
    ACCESS_APPROVE = "access:approve"
```
- Kotlin: `enum class Scope(val value: String)`.
- So sánh được với chuỗi, ghi ra JSON là chuỗi: hợp cho reason code, status, scope.

## 8. Decorator `@...`: "bọc thêm hành vi quanh một hàm"

```python
@harness_tool(name="get_ticket", description="...", args_schema=GetTicketArgs, scope=Scope.TICKET_READ)
async def get_ticket(ctx: ToolContext, args: GetTicketArgs) -> ToolResult[TicketView]:
    ...
```
- `@x` đặt trên hàm = "đưa hàm này cho `x`, dùng thứ `x` trả về thay cho hàm gốc".
- Ở đây: hàm nghiệp vụ được bọc thành một LangChain tool có kiểm tra quyền, event, map lỗi.
- Kotlin gần nhất: annotation + code generation, hoặc hàm bậc cao `wrap { ... }`. Android: OkHttp Interceptor.
- `@classmethod` = hàm gọi trên class (`Decision.allow()`), như `companion object`. `@property` = getter.

## 9. Generic: "khuôn dùng cho nhiều kiểu"

```python
class ToolResult(BaseModel, Generic[T_co], frozen=True): ...   # cách cũ
def harness_tool[A: BaseModel, T](...) -> ...: ...             # cách mới (Python 3.12+)
```
- `ToolResult[TicketView]` = Kotlin `ToolResult<TicketView>`.
- `[A: BaseModel, T]` sau tên hàm = khai báo tham số kiểu; `A: BaseModel` = `A` phải là pydantic model (Kotlin: `<A : BaseModel, T>`).
- `Callable[[ToolContext, A], Awaitable[ToolResult[T]]]` = "một hàm async nhận `(ToolContext, A)` và trả `ToolResult[T]`" (Kotlin: `suspend (ToolContext, A) -> ToolResult<T>`).

**Đọc nhanh:** khi gặp generic, chỉ cần hỏi "khuôn này bọc kiểu gì".

## 10. Vài cú pháp ngắn hay gặp

| Cú pháp | Nghĩa | Kotlin |
|---|---|---|
| `f"dept:{department.value}"` | Chuỗi có chèn biến | `"dept:${department.value}"` |
| `[t.id for t in tickets if t.open]` | List comprehension: lọc + biến đổi | `tickets.filter { it.open }.map { it.id }` |
| `x if cond else y` | Biểu thức điều kiện | `if (cond) x else y` |
| `a \| b` (với set) | Hợp hai tập | `a union b` |
| `try: ... except DomainError as exc: ...` | Bắt lỗi | `try { } catch (e: DomainError) { }` |
| `raise X(...)` | Ném lỗi | `throw X(...)` |
| `self` | Đối tượng hiện tại | `this` |
| `_ten` | Quy ước "nội bộ, đừng dùng từ ngoài" | `private` (không bắt buộc) |
| `type Currency = Literal["VND"]` | Alias kiểu; `Literal` = chỉ nhận đúng giá trị đó | `typealias` + sealed/enum |
| `**kwargs`, `*args` | Nhận thêm tham số tùy ý (có tên / không tên) | `vararg` |

---

## Cách đọc một file nhanh

1. Đọc **docstring** đầu file và đầu class (chuỗi `"""..."""`): nó nói file này làm gì.
2. Đọc **tên và chữ ký hàm** (tham số, kiểu trả về), chưa đọc thân hàm.
3. Tìm các **khối**: kiểm tra (`if ... raise/return`), gọi I/O (`await`), xử lý lỗi (`try/except`), trả kết quả (`return`).
4. Chỉ đọc kỹ từng dòng ở khối liên quan tới câu hỏi của bạn.
5. Không hiểu một dòng? Hỏi Claude Code: *"dòng X ở file:dòng làm gì, nói theo mẫu số mấy trong cheat sheet"*.
