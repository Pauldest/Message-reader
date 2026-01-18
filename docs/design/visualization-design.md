# Visualization Module Design Document

## Module Overview

**Module Name**: Knowledge Graph Visualization
**Location**: `src/visualization.py`
**Purpose**: Generate interactive HTML visualizations of the entity knowledge graph using vis.js network library.

**Key Features**:
- Interactive force-directed graph layout
- Color-coded entity types
- Size scaled by mention frequency
- Relationship visualization with directional arrows
- Clickable nodes for detail inspection
- Self-contained HTML export

---

## File Structure

```
src/
└── visualization.py              # Graph generation (200+ lines)
```

**Output**:
```
data/
└── knowledge_graph.html          # Interactive visualization
```

**Lines of Code**: ~200 lines
**Complexity**: Low-Medium (primarily data transformation and templating)

---

## Architecture Diagram

```
┌──────────────────┐
│  EntityStore     │ (Database with entities & relations)
│                  │
│  - entities      │
│  - entity_       │
│    relations     │
└────────┬─────────┘
         │
         │ query
         ▼
┌──────────────────────────────────────────┐
│  generate_knowledge_graph_html()         │
│                                          │
│  1. Query entities & relations from DB   │
│  2. Transform to vis.js format           │
│  3. Inject into HTML template            │
│  4. Write to file                        │
└──────────────────┬───────────────────────┘
                   │
                   │ generates
                   ▼
        ┌─────────────────────┐
        │  knowledge_graph    │
        │  .html              │
        │                     │
        │  - vis.js library   │
        │  - nodes[]          │
        │  - edges[]          │
        │  - physics engine   │
        │  - interactions     │
        └─────────────────────┘
```

---

## Key Components

### 1. HTML Template

**Self-contained HTML with embedded vis.js library.**

```python
HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Knowledge Graph Visualization</title>
  <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <style type="text/css">
    body { font-family: sans-serif; margin: 0; padding: 20px; }
    #mynetwork {
      width: 100%;
      height: 800px;
      border: 1px solid lightgray;
      background-color: #f9f9f9;
    }
    .legend { margin-bottom: 10px; }
    .legend span { margin-right: 15px; font-size: 14px; }
  </style>
</head>
<body>

<div class="header">
  <h2>Knowledge Graph Visualization</h2>
  <div class="legend">
    <span style="color: #97C2FC">● Company</span>
    <span style="color: #FB7E81">● Person</span>
    <span style="color: #7BE141">● Product</span>
    <span style="color: #FFC0CB">● Org</span>
    <span style="color: #EB7DF4">● Concept</span>
  </div>
</div>

<div id="mynetwork"></div>

<script type="text/javascript">
  // Data injected by Python
  var nodesArray = __NODES_JSON__;
  var edgesArray = __EDGES_JSON__;

  var nodes = new vis.DataSet(nodesArray);
  var edges = new vis.DataSet(edgesArray);

  var container = document.getElementById('mynetwork');
  var data = { nodes: nodes, edges: edges };

  var options = {
    nodes: {
      shape: 'dot',
      size: 20,
      font: { size: 14, color: '#333' },
      borderWidth: 2
    },
    edges: {
      width: 1,
      arrows: { to: { enabled: true, scaleFactor: 0.5 } },
      color: { color: '#848484', highlight: '#848484', hover: '#848484' },
      smooth: { type: 'continuous' }
    },
    physics: {
      forceAtlas2Based: {
        gravitationalConstant: -50,
        centralGravity: 0.01,
        springLength: 100,
        springConstant: 0.08
      },
      maxVelocity: 50,
      solver: 'forceAtlas2Based',
      timestep: 0.35,
      stabilization: { iterations: 150 }
    },
    interaction: {
        hover: true,
        tooltipDelay: 200
    }
  };

  var network = new vis.Network(container, data, options);

  network.on("click", function (params) {
      if (params.nodes.length > 0) {
          var nodeId = params.nodes[0];
          var node = nodes.get(nodeId);
          console.log("Clicked node:", node);
      }
  });
</script>
</body>
</html>
"""
```

**Template Features**:
- **vis.js CDN**: Loads from unpkg CDN
- **Legend**: Color-coded entity types
- **Responsive**: 100% width, 800px height
- **Interactive**: Click handling, hover tooltips
- **Physics Engine**: Force-directed layout

---

### 2. Main Generation Function

```python
def generate_knowledge_graph_html(
    entity_store: EntityStore,
    output_path: str = "data/knowledge_graph.html"
):
    """
    Generate interactive HTML visualization of knowledge graph.

    Args:
        entity_store: EntityStore instance with populated graph
        output_path: Output file path

    Returns:
        None (writes HTML file)
    """
    logger.info("generating_visualization", output=output_path)

    # 1. Fetch entities and relations from database
    with entity_store.db._get_conn() as conn:
        cursor = conn.cursor()

        # Query entities
        cursor.execute("SELECT id, canonical_name, type, mention_count FROM entities")
        entities = cursor.fetchall()

        # Query relations
        cursor.execute("SELECT source_id, target_id, relation_type, confidence FROM entity_relations")
        relations = cursor.fetchall()

    # 2. Transform to vis.js format
    nodes = []
    color_map = {
        "COMPANY": "#97C2FC",  # Blue
        "PERSON": "#FB7E81",   # Red
        "PRODUCT": "#7BE141",  # Green
        "ORG": "#FFC0CB",      # Pink
        "CONCEPT": "#EB7DF4",  # Purple
    }

    for e in entities:
        e_type = e['type'].upper() if e['type'] else "COMPANY"
        color = color_map.get(e_type, "#97C2FC")

        # Scale node size by mention count
        size = 20 + min(e['mention_count'] * 2, 30)  # Cap at 50px

        nodes.append({
            "id": e['id'],
            "label": e['canonical_name'],
            "title": f"Type: {e_type}<br>Mentions: {e['mention_count']}",  # Tooltip
            "color": color,
            "size": size,
            "group": e_type
        })

    edges = []
    for r in relations:
        edges.append({
            "from": r['source_id'],
            "to": r['target_id'],
            "label": r['relation_type'],
            "title": f"{r['relation_type']} (confidence: {r['confidence']:.2f})",
            "width": 1 + r['confidence'],  # Thicker edges for higher confidence
        })

    # 3. Inject data into HTML template
    nodes_json = json.dumps(nodes, ensure_ascii=False, indent=2)
    edges_json = json.dumps(edges, ensure_ascii=False, indent=2)

    html_content = HTML_TEMPLATE.replace("__NODES_JSON__", nodes_json)
    html_content = html_content.replace("__EDGES_JSON__", edges_json)

    # 4. Write to file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html_content, encoding='utf-8')

    logger.info("visualization_generated",
               nodes=len(nodes),
               edges=len(edges),
               output=output_path)
```

---

## Data Flow

```
EntityStore Database
    │
    ├─► SELECT entities (id, canonical_name, type, mention_count)
    │
    └─► SELECT entity_relations (source_id, target_id, relation_type, confidence)
        │
        ▼
Transform to vis.js format
    │
    ├─► Nodes: [
    │     {id, label, color, size, title, group},
    │     ...
    │   ]
    │
    └─► Edges: [
          {from, to, label, title, width},
          ...
        ]
        │
        ▼
Inject into HTML Template
    │
    └─► Replace __NODES_JSON__ and __EDGES_JSON__
        │
        ▼
Write to file (data/knowledge_graph.html)
```

---

## Visualization Features

### Node Representation

**Properties**:
- **id**: Entity ID from database
- **label**: Entity canonical name (displayed)
- **color**: Type-specific color (see color_map)
- **size**: Scaled by mention_count (20-50px)
- **title**: Tooltip showing type and mentions
- **group**: Entity type for clustering

**Size Calculation**:
```python
size = 20 + min(mention_count * 2, 30)
```
- Base size: 20px
- Scaling: +2px per mention
- Cap: 50px maximum

**Example Node**:
```json
{
  "id": 15,
  "label": "OpenAI",
  "color": "#97C2FC",
  "size": 50,
  "title": "Type: COMPANY<br>Mentions: 25",
  "group": "COMPANY"
}
```

### Edge Representation

**Properties**:
- **from**: Source entity ID
- **to**: Target entity ID
- **label**: Relation type (e.g., "ceo_of", "competitor")
- **title**: Tooltip with relation and confidence
- **width**: Scaled by confidence (1-2px)
- **arrows**: Directional (→)

**Width Calculation**:
```python
width = 1 + confidence  # 1-2px based on confidence
```

**Example Edge**:
```json
{
  "from": 12,
  "to": 15,
  "label": "ceo_of",
  "title": "ceo_of (confidence: 0.95)",
  "width": 1.95
}
```

---

## Physics Configuration

**Force-Directed Layout** using ForceAtlas2 algorithm:

```javascript
physics: {
  forceAtlas2Based: {
    gravitationalConstant: -50,     // Repulsion between nodes
    centralGravity: 0.01,           // Attraction to center
    springLength: 100,              // Edge length
    springConstant: 0.08            // Edge stiffness
  },
  maxVelocity: 50,
  solver: 'forceAtlas2Based',
  timestep: 0.35,
  stabilization: { iterations: 150 }
}
```

**Effects**:
- Nodes repel each other (prevent overlap)
- Edges pull connected nodes together
- Highly connected nodes form clusters
- Graph stabilizes after 150 iterations

---

## Interaction Features

### 1. Hover Tooltips

```javascript
interaction: {
    hover: true,
    tooltipDelay: 200  // 200ms delay
}
```

**Shows**:
- Node: Entity type + mention count
- Edge: Relation type + confidence

### 2. Click Events

```javascript
network.on("click", function (params) {
    if (params.nodes.length > 0) {
        var nodeId = params.nodes[0];
        var node = nodes.get(nodeId);
        console.log("Clicked node:", node);
        // Potential: Show detail panel, navigate to entity page, etc.
    }
});
```

### 3. Zoom & Pan

- **Mouse wheel**: Zoom in/out
- **Click + drag**: Pan the canvas
- **Pinch gesture**: Mobile zoom

---

## Usage Examples

### Basic Usage

```python
from src.storage.entity_store import EntityStore
from src.visualization import generate_knowledge_graph_html

# Initialize entity store
entity_store = EntityStore(db_path="data/articles.db")

# Generate visualization
generate_knowledge_graph_html(
    entity_store=entity_store,
    output_path="data/knowledge_graph.html"
)

# Open in browser
import webbrowser
webbrowser.open("data/knowledge_graph.html")
```

### Integration with Email

```python
# Generate graph visualization
generate_knowledge_graph_html(entity_store, "data/temp_graph.html")

# Attach to email
from src.notifier.email_sender import EmailSender
email_sender = EmailSender(config.email)

# Read HTML as attachment
with open("data/temp_graph.html", "rb") as f:
    html_content = f.read()

await email_sender.send_digest(
    digest=digest,
    attachments=[
        ("knowledge_graph.html", html_content, "text/html")
    ]
)
```

### CLI Integration

```python
# In main.py or CLI
import click

@click.command()
def visualize_graph():
    """Generate knowledge graph visualization"""
    config = get_config()
    entity_store = EntityStore(config.storage.database_path)

    output_path = "data/knowledge_graph.html"
    generate_knowledge_graph_html(entity_store, output_path)

    click.echo(f"✅ Visualization generated: {output_path}")
    click.echo(f"📊 Open in browser to view")

    # Optional: Auto-open in browser
    if click.confirm("Open in browser?"):
        import webbrowser
        webbrowser.open(output_path)
```

---

## Design Patterns Used

### 1. Template Method Pattern
- HTML template with placeholders
- Data injection at runtime

### 2. Data Transformation Pipeline
- Query → Transform → Inject → Write

### 3. Color Coding Pattern
- Entity types mapped to distinct colors
- Visual differentiation

---

## Error Handling

```python
def generate_knowledge_graph_html(entity_store, output_path):
    try:
        logger.info("generating_visualization", output=output_path)

        # Query database
        with entity_store.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, canonical_name, type, mention_count FROM entities")
            entities = cursor.fetchall()

            cursor.execute("SELECT source_id, target_id, relation_type, confidence FROM entity_relations")
            relations = cursor.fetchall()

        if not entities:
            logger.warning("no_entities_found")
            return

        # Transform and generate
        nodes = [transform_entity(e) for e in entities]
        edges = [transform_relation(r) for r in relations]

        html_content = inject_data(HTML_TEMPLATE, nodes, edges)

        # Write file
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html_content, encoding='utf-8')

        logger.info("visualization_generated", nodes=len(nodes), edges=len(edges))

    except Exception as e:
        logger.error("visualization_failed", error=str(e))
        raise
```

---

## Performance Considerations

### 1. Database Queries
- Single query for entities
- Single query for relations
- No N+1 query problem

### 2. JSON Serialization
- `ensure_ascii=False` for unicode support
- `indent=2` for readability (can be removed for production)

### 3. File Size
- Typical: 50-200KB for 100-500 entities
- Scales linearly with entity count

### 4. Browser Performance
- vis.js handles up to ~1000 nodes efficiently
- Beyond that, consider filtering or clustering

---

## Testing Strategy

### Unit Tests

```python
def test_generate_visualization(tmp_path):
    # Setup
    db_path = tmp_path / "test.db"
    entity_store = EntityStore(db_path)

    # Add test entities
    entity_store.add_entity("OpenAI", "COMPANY")
    entity_store.add_entity("Sam Altman", "PERSON")
    entity_store.add_relation(1, 2, "ceo_of", 0.95)

    # Generate visualization
    output_path = tmp_path / "graph.html"
    generate_knowledge_graph_html(entity_store, str(output_path))

    # Verify
    assert output_path.exists()
    html_content = output_path.read_text()
    assert "OpenAI" in html_content
    assert "Sam Altman" in html_content
    assert "ceo_of" in html_content
```

### Integration Tests

```python
def test_full_pipeline(config):
    # Run full analysis to populate graph
    service = RSSReaderService(config)
    await service.run_once(limit=10)

    # Generate visualization
    generate_knowledge_graph_html(
        service.entity_store,
        "data/test_graph.html"
    )

    # Verify
    assert Path("data/test_graph.html").exists()
```

---

## Future Enhancements

### 1. Interactive Filters
```javascript
// Filter by entity type
function filterByType(type) {
    nodes.get().forEach(node => {
        if (node.group !== type) {
            nodes.update({id: node.id, hidden: true});
        } else {
            nodes.update({id: node.id, hidden: false});
        }
    });
}
```

### 2. Time-Based Animation
- Visualize how graph evolves over time
- Playback control (play, pause, scrub)
- Highlight new entities/relations

### 3. Detail Panels
```javascript
network.on("click", function (params) {
    if (params.nodes.length > 0) {
        var nodeId = params.nodes[0];
        showDetailPanel(nodeId);  // Show sidebar with entity details
    }
});
```

### 4. Export Options
- Export as PNG/SVG
- Export as JSON for other tools
- Share link generation

### 5. Advanced Layouts
- Hierarchical layout for organizational charts
- Circular layout for timeline visualization
- Custom layouts based on entity attributes

---

## Dependencies

### Internal
- `src/storage/entity_store.py`: EntityStore

### External
- `json`: Data serialization
- `pathlib`: File handling
- `structlog`: Logging

### Frontend
- `vis-network`: Graph visualization library (CDN)

---

## Configuration

```yaml
visualization:
  output_path: "data/knowledge_graph.html"
  auto_open: false  # Auto-open in browser

  # Optional: Advanced settings
  max_nodes: 1000  # Limit for performance
  physics_enabled: true
  layout: "forceAtlas2Based"  # or "hierarchical", "circular"
```

---

## Summary

The Visualization module provides **interactive knowledge graph visualization** with:

**Strengths**:
- ✅ Self-contained HTML (no server required)
- ✅ Interactive force-directed layout
- ✅ Color-coded entity types
- ✅ Size scaled by importance
- ✅ Hover tooltips and click events
- ✅ Easy to share (single HTML file)

**Use Cases**:
- 🎯 Explore entity relationships
- 🎯 Understand knowledge graph structure
- 🎯 Debug entity extraction quality
- 🎯 Attach to email digests
- 🎯 Embed in dashboards

**Best Practices**:
- Generate after significant graph updates
- Filter to top N entities for performance
- Use for exploratory analysis
- Combine with detail views for depth

This module transforms abstract knowledge graphs into **intuitive visual representations** that make complex entity relationships immediately understandable.
