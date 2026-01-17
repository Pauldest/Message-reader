
import json
import structlog
from pathlib import Path
from src.storage.entity_store import EntityStore

logger = structlog.get_logger()

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
  var data = {
    nodes: nodes,
    edges: edges
  };
  
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
          // Potential detail view logic
      }
  });
</script>
</body>
</html>
"""

def generate_knowledge_graph_html(entity_store: EntityStore, output_path: str = "data/knowledge_graph.html"):
    """
    Generate an interactive HTML visualization of the knowledge graph using vis.js
    """
    logger.info("generating_visualization", output=output_path)
    
    # 1. Fetch data
    with entity_store.db._get_conn() as conn:
        cursor = conn.cursor()
        
        # Nodes (Entities)
        cursor.execute("SELECT id, canonical_name, type, mention_count FROM entities")
        entities = cursor.fetchall()
        
        # Edges (Relations)
        cursor.execute("SELECT source_id, target_id, relation_type, confidence FROM entity_relations")
        relations = cursor.fetchall()
        
    # 2. Format for vis.js
    nodes = []
    
    # Color mapping for entity types
    color_map = {
        "COMPANY": "#97C2FC", # Blue
        "PERSON": "#FB7E81",  # Red
        "PRODUCT": "#7BE141", # Green
        "ORG": "#FFC0CB",     # Pink
        "CONCEPT": "#EB7DF4", # Purple
    }
    
    for e in entities:
        e_type = e['type'].upper() if e['type'] else "COMPANY"
        color = color_map.get(e_type, "#97C2FC")
        
        # Scale size by mentions (log scale or simple cap)
        size = 20 + min(e['mention_count'] * 2, 30)
        
        nodes.append({
            "id": e['id'],
            "label": e['canonical_name'],
            "title": f"Type: {e_type}<br>Mentions: {e['mention_count']}", # Tooltip
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
            "title": f"Relation: {r['relation_type']}<br>Conf: {r['confidence']}",
            "font": { "align": "middle", "size": 10 }
        })
        
    # 3. Inject into template
    html_content = HTML_TEMPLATE.replace(
        "__NODES_JSON__", json.dumps(nodes)
    ).replace(
        "__EDGES_JSON__", json.dumps(edges)
    )
    
    # 4. Write file
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html_content, encoding="utf-8")
    
    logger.info("visualization_generated", nodes=len(nodes), edges=len(edges))
    return str(out_file.absolute())
