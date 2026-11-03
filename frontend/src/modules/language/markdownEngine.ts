import {EditorState,StateField,type EditorSelection} from '@codemirror/state';
import {markdown,markdownLanguage} from '@codemirror/lang-markdown';
import {syntaxTree,ensureSyntaxTree} from '@codemirror/language';
import {minimalSetup} from 'codemirror';
import {Decoration,EditorView,ViewPlugin,WidgetType,keymap,type DecorationSet,type ViewUpdate} from '@codemirror/view';

export type Format='heading-1'|'heading-2'|'heading-3'|'heading-4'|'heading-5'|'heading-6'|'rule'|'bold'|'italic'|'bold-italic'|'highlight';
export type EditorAction='cut'|'copy'|'paste'|'table';
export interface EditorMenu{x:number;y:number;selected:boolean;tableAllowed:boolean;}
export interface MarkdownEngine{format:(kind:Format)=>void;contextAction:(kind:EditorAction)=>Promise<void>;closeContext:(restore:boolean)=>void;destroy:()=>void;}
type SyntaxNode=ReturnType<ReturnType<typeof syntaxTree>['resolveInner']>;

function activeTable(state:EditorState,position=state.selection.main.head){
  const tree=ensureSyntaxTree(state,position,30)??syntaxTree(state);
  let node:SyntaxNode|null=tree.resolveInner(position,-1);
  while(node&&node.name!=='Table')node=node.parent;
  return node;
}
function rowColumns(state:EditorState,row:SyntaxNode){
  const pipes=row.getChildren('TableDelimiter');
  const leading=pipes.length>0&&!state.doc.sliceString(row.from,pipes[0].from).trim();
  const trailing=pipes.length>0&&!state.doc.sliceString(pipes.at(-1)!.to,row.to).trim();
  return {count:pipes.length+1-Number(leading)-Number(trailing),trailing};
}
function tableRows(table:SyntaxNode){return [table.getChild('TableHeader')!,...table.getChildren('TableRow')];}
function growTable(view:EditorView,position:number,column:boolean){
  const table=activeTable(view.state,position);
  if(!table)return;
  const rows=tableRows(table),columns=rowColumns(view.state,rows[0]).count;
  if(rows.some(row=>rowColumns(view.state,row).count!==columns))return;
  if(column){
    const separator=table.getChild('TableDelimiter')!;
    const changes=[...rows,separator].sort((a,b)=>a.from-b.from).map(row=>{
      const isSeparator=row===separator;
      const trailing=isSeparator?view.state.doc.sliceString(row.from,row.to).trimEnd().endsWith('|'):rowColumns(view.state,row).trailing;
      return {from:row.to,insert:(trailing?' ':' | ')+(isSeparator?'---':'')+' |'};
    });
    view.dispatch({changes,selection:view.state.selection.map(view.state.changes(changes),-1),userEvent:'input.table-column'});
  }else{
    const last=rows.at(-1)!;
    const line=view.state.doc.lineAt(last.from);
    const prefix=view.state.doc.sliceString(line.from,last.from);
    const changes={from:table.to,insert:'\n'+prefix+'|'+Array(columns).fill('  |').join('')};
    view.dispatch({changes,selection:view.state.selection.map(view.state.changes(changes),-1),userEvent:'input.table-row'});
  }
  view.focus();
}
class TableGrow extends WidgetType{
  constructor(readonly position:number,readonly column:boolean,readonly available:boolean){super();}
  eq(other:TableGrow){return this.position===other.position&&this.column===other.column&&this.available===other.available;}
  toDOM(view:EditorView){
    const button=document.createElement('button');
    button.type='button';button.className='cm-table-grow';
    button.setAttribute('aria-label',this.column?'Add table column':'Add table row');
    button.title=this.available?(this.column?'Add one column':'Add one row'):'Match every row to the header before expanding this table.';
    button.disabled=!this.available;
    button.onmousedown=event=>event.preventDefault();
    button.onclick=()=>growTable(view,this.position,this.column);
    if(this.column)return button;
    const edge=document.createElement('div');edge.className='cm-table-bottom';edge.append(button);return edge;
  }
  ignoreEvent(){return true;}
}
function tableDecorations(state:EditorState){
  const table=activeTable(state);
  if(!table)return Decoration.none;
  const rows=tableRows(table),columns=rowColumns(state,rows[0]).count;
  const available=rows.every(row=>rowColumns(state,row).count===columns);
  const lines=[...rows,table.getChild('TableDelimiter')!];
  const widest=lines.reduce((a,b)=>b.to-b.from>a.to-a.from?b:a);
  return Decoration.set([
    Decoration.widget({widget:new TableGrow(table.from+1,true,available),side:1}).range(widest.to),
    Decoration.widget({widget:new TableGrow(table.from+1,false,available),block:true,side:1}).range(table.to),
  ],true);
}
const tableField=StateField.define<DecorationSet>({
  create:tableDecorations,
  update:(decorations,transaction)=>transaction.docChanged||transaction.selection||syntaxTree(transaction.state)!==syntaxTree(transaction.startState)?tableDecorations(transaction.state):decorations,
  provide:field=>EditorView.decorations.from(field),
});

function isLiteral(state:EditorState,position:number){
  let node:ReturnType<ReturnType<typeof syntaxTree>['resolveInner']>|null=syntaxTree(state).resolveInner(position,1);
  while(node){
    if(['InlineCode','FencedCode','CodeBlock','HTMLBlock'].includes(node.name))return true;
    node=node.parent;
  }
  return false;
}
function escaped(line:string,index:number){
  let slashes=0;
  for(let at=index-1;at>=0&&line[at]==='\\';at--)slashes++;
  return slashes%2===1;
}
function highlights(editor:EditorView):DecorationSet{
  const marks=[];
  for(const range of editor.visibleRanges){
    let line=editor.state.doc.lineAt(range.from);
    while(line.from<=range.to){
      const pattern=/==([^=\n]|=(?!=))+==/g;
      for(const match of line.text.matchAll(pattern)){
        const start=match.index??0;
        if(escaped(line.text,start)||isLiteral(editor.state,line.from+start))continue;
        const from=line.from+start+2,to=line.from+start+match[0].length-2;
        if(from<to)marks.push(Decoration.mark({class:'cm-markdown-highlight'}).range(from,to));
      }
      if(line.to===editor.state.doc.length)break;
      line=editor.state.doc.line(line.number+1);
    }
  }
  return Decoration.set(marks,true);
}
const highlightPlugin=ViewPlugin.fromClass(class{
  decorations:DecorationSet;
  constructor(editor:EditorView){this.decorations=highlights(editor);}
  update(update:ViewUpdate){if(update.docChanged||update.viewportChanged)this.decorations=highlights(update.view);}
},{decorations:plugin=>plugin.decorations});

export function mountMarkdownEditor(host:HTMLDivElement,value:string,label:string,onChange:(text:string)=>void,onContext:(menu:EditorMenu)=>void):MarkdownEngine{
  let view:EditorView;
  let alive=true;
  let context:{doc:EditorState['doc'];selection:EditorSelection}|null=null;
  function openContext(x:number,y:number){
    context={doc:view.state.doc,selection:view.state.selection};
    onContext({x,y,selected:view.state.selection.ranges.some(range=>!range.empty),tableAllowed:!isLiteral(view.state,view.state.selection.main.head)});
  }
  function closeContext(restore:boolean){
    const saved=context;context=null;
    if(restore&&alive){
      if(saved?.doc===view.state.doc)view.dispatch({selection:saved.selection});
      view.focus();
    }
  }
  async function contextAction(kind:EditorAction){
    const saved=context;
    if(!alive||!saved||saved.doc!==view.state.doc)throw new Error('The note changed. Open the menu again at the current cursor.');
    const selected=saved.selection.ranges.map(range=>saved.doc.sliceString(range.from,range.to)).join('\n');
    let paste='';
    if(kind!=='table'){
      try{
        if(kind==='paste')paste=await navigator.clipboard.readText();
        else if(selected)await navigator.clipboard.writeText(selected);
        else return;
      }catch{
        const shortcut=kind==='paste'?'Ctrl+V':kind==='cut'?'Ctrl+X':'Ctrl+C';
        throw new Error(`Clipboard access was blocked. Press Escape, then ${shortcut} in the editor.`);
      }
    }
    if(!alive||context!==saved||view.state.doc!==saved.doc)throw new Error('The note or cursor changed. Open the menu again.');
    view.dispatch({selection:saved.selection});
    if(kind==='table'){
      const position=saved.selection.main.head;
      if(isLiteral(view.state,position))throw new Error('Move the cursor outside code or HTML to insert a table.');
      const before=saved.doc.sliceString(0,position),after=saved.doc.sliceString(position);
      const left=!before||before.endsWith('\n\n')?'':before.endsWith('\n')?'\n':'\n\n';
      const right=!after?'\n':after.startsWith('\n\n')?'':after.startsWith('\n')?'\n':'\n\n';
      const table='|  |  |\n| --- | --- |\n|  |  |';
      view.dispatch({changes:{from:position,insert:left+table+right},selection:{anchor:position+left.length+2},userEvent:'input.table-insert'});
    }else if(kind==='cut'||kind==='paste'&&paste){
      view.dispatch({...view.state.replaceSelection(kind==='cut'?'':paste),userEvent:kind==='cut'?'input.clipboard-cut':'input.paste'});
    }
  }
  function surround(mark:string){
    const selection=view.state.selection.main;
    const selected=view.state.doc.sliceString(selection.from,selection.to);
    view.dispatch({
      changes:{from:selection.from,to:selection.to,insert:mark+selected+mark},
      selection:{anchor:selection.from+mark.length,head:selection.to+mark.length},
    });
    view.focus();
  }
  function format(kind:Format){
    if(kind.startsWith('heading-')){
      const count=Number(kind.slice(-1));
      const line=view.state.doc.lineAt(view.state.selection.main.from);
      const prefix=/^#{1,6}[ \t]+/.exec(line.text);
      view.dispatch({changes:{from:line.from,to:line.from+(prefix?.[0].length??0),insert:'#'.repeat(count)+' '}});
      view.focus();
    }else if(kind==='rule'){
      const selection=view.state.selection.main;
      const before=view.state.doc.sliceString(0,selection.from);
      const after=view.state.doc.sliceString(selection.to);
      const left=!before||before.endsWith('\n\n')?'':before.endsWith('\n')?'\n':'\n\n';
      const right=!after?'\n':after.startsWith('\n\n')?'':after.startsWith('\n')?'\n':'\n\n';
      const insert=left+'---'+right;
      view.dispatch({changes:{from:selection.from,to:selection.to,insert},selection:{anchor:selection.from+insert.length}});
      view.focus();
    }else surround(kind==='bold'?'**':kind==='italic'?'*':kind==='bold-italic'?'***':'==');
  }
  view=new EditorView({parent:host,state:EditorState.create({doc:value,extensions:[
    minimalSetup,
    markdown({base:markdownLanguage,completeHTMLTags:false,pasteURLAsLink:false}),
    EditorView.lineWrapping,
    EditorView.contentAttributes.of({'aria-label':label}),
    keymap.of([
      {key:'Mod-b',run:()=>{format('bold');return true;}},
      {key:'Mod-i',run:()=>{format('italic');return true;}},
    ]),
    highlightPlugin,
    tableField,
    EditorView.domEventHandlers({
      contextmenu:(event,editor)=>{
        event.preventDefault();event.stopPropagation();
        const position=editor.posAtCoords({x:event.clientX,y:event.clientY});
        const selection=editor.state.selection.main;
        if(position!==null&&(selection.empty||position<selection.from||position>selection.to))editor.dispatch({selection:{anchor:position}});
        openContext(event.clientX,event.clientY);return true;
      },
      keydown:event=>{
        if(event.key!=='ContextMenu'&&!(event.shiftKey&&event.key==='F10'))return false;
        event.preventDefault();event.stopPropagation();
        const caret=view.coordsAtPos(view.state.selection.main.head),bounds=host.getBoundingClientRect();
        openContext(caret?.left??bounds.left+16,caret?.bottom??bounds.top+16);return true;
      },
    }),
    EditorView.updateListener.of(update=>{if(update.docChanged)onChange(update.state.doc.toString());}),
    EditorView.theme({
      '&':{height:'100%',backgroundColor:'#101016',color:'#eee'},
      '.cm-scroller':{overflow:'auto',fontFamily:'ui-monospace,SFMono-Regular,Consolas,monospace'},
      '.cm-content':{minHeight:'100%',padding:'24px',fontSize:'15px',lineHeight:'1.65',caretColor:'#eee'},
      '.cm-gutters':{backgroundColor:'#17171f',color:'#777787',borderRight:'1px solid #292936'},
      '.cm-cursor':{borderLeftColor:'#eee'},
      '.cm-selectionBackground':{backgroundColor:'#51406e !important'},
      '.cm-markdown-highlight':{backgroundColor:'#8e6a2d88',borderRadius:'2px'},
      '.cm-table-grow':{display:'inline-block',width:'28px',height:'28px',marginLeft:'8px',border:'1px solid #424252',borderRadius:'50%',background:'#242431',color:'#eee',cursor:'pointer',fontSize:'20px',lineHeight:'24px',opacity:'.65'},
      '.cm-table-grow::before':{content:'"+"'},
      '.cm-content:hover .cm-table-grow,.cm-table-grow:focus-visible':{opacity:'1'},
      '.cm-table-grow:hover,.cm-table-grow:focus-visible':{background:'#424252',outline:'2px solid var(--accent)'},
      '.cm-table-grow:disabled':{opacity:'.35',cursor:'default'},
      '.cm-table-bottom':{padding:'4px 0 8px'},
      '&.cm-focused':{outline:'2px solid var(--accent)',outlineOffset:'-2px'},
    }),
  ]})});
  return {format,contextAction,closeContext,destroy:()=>{alive=false;context=null;view.destroy();}};
}
