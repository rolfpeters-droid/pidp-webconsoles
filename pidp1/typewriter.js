const nbstag = (n) => '<span style="position:relative; left:-' + String(n) + 'ch">';

class Typewriter {
	constructor(container, content, inputEl) {
		this.content = content;
		this.container = container;
		this.clear();
		// inputEl (los <textarea>-veld) vangt de toetsaanslagen op i.p.v. de
		// container zelf -- nodig voor het mobiele schermtoetsenbord. Valt
		// terug op de container als er geen apart veld is meegegeven.
		const target = inputEl || container;
		target.addEventListener('keydown', (ev) => this.keydown(ev));
		if (inputEl) {
			// Mobiele schermtoetsenborden (Gboard e.d.) leveren voor gewone
			// tekens vaak geen bruikbare keydown -- die komt binnen als
			// key === "Unidentified" / keyCode 229 (IME-compositie). De
			// daadwerkelijke tekens komen dan pas via het input-event, met
			// ev.inputType/ev.data. Dat vangen we hier apart op.
			inputEl.addEventListener('input', (ev) => this.inputEvent(ev, inputEl));
		}
	}

	sendCode(code) {
		if (code >= 0) {
	//		console.log("sent", code);
			ws.send(JSON.stringify({ type: 'key', value: code & 0o377 }));
		}
	}

	keydown(k) {
		// Laat IME-compositietoetsen (mobiel schermtoetsenbord) over aan
		// inputEvent() hieronder -- anders versturen we niks bruikbaars hier
		// en missen we het daadwerkelijke teken dat er via input aankomt.
		if (k.key === 'Unidentified' || k.keyCode === 229) return;

		k.preventDefault();

		let key = k.key;
		let code = -1
		if(key.length == 1)
			code = key.charCodeAt(0);
		else switch(key) {
		case "Backspace": code = 0o10; break;
		case "Tab": code = 0o11; break;
		case "Enter": code = 0o15; break;
		}

		this.sendCode(code);
	}

	inputEvent(ev, inputEl) {
		const type = ev.inputType;
		const data = ev.data;
		inputEl.value = '';	// nooit tekst laten opbouwen in het onzichtbare veld

		if (type === 'deleteContentBackward') { this.sendCode(0o10); return; }
		if (type === 'insertLineBreak')       { this.sendCode(0o15); return; }
		if (data) {
			for (const ch of data)
				this.sendCode(ch.charCodeAt(0));
		}
	}

	clear() {
		this.isred = false;
		this.page = "";
		this.nbs = 0;
		this.line = "";
		this.linepos = 0;
		this.endline = "";
		this.update("_");
	}

	update(line) {
		this.content.innerHTML = this.page + line + this.endline;
		this.container.scrollTop = this.container.scrollHeight;
	}

	red() {
		this.line += '<span class="red">';
		this.endline += '</span>';
		this.isred = true;
		this.update(this.line + "_");
	}

	black() {
		this.line += '<span class="black">';
		this.endline += '</span>';
		this.isred = false;
		this.update(this.line + "_");
	}

	isspacing(c) {
		if(c == '‾' || c == '|' ||
		   c == '·' || c == '_')
			return false;
		return true;
	}

	printchar(c) {
		if(c == '\b') {
			if(this.linepos > 0) {
				this.linepos--;
				this.nbs++;
			}
			let tmpline = this.line + nbstag(this.nbs) + "_</span>" + this.endline;
			this.update(tmpline);
			return;
		}
		if(this.nbs > 0) {
			this.line += nbstag(this.nbs);
			this.endline += "</span>";
			this.nbs = 0;
		}

		if(c == '<') c = '&lt;';
		else if(c == '>') c = '&gt;';
		else if(c == '&') c = '&amp;';	// not in charset actually
		else if(c == '~') c = '˜';

		this.line += c;
		if(c == '\t')
			this.linepos = (this.linepos+7)&~7;
		else
			this.linepos++;
		if(c == '\n') {
			this.page += this.line + this.endline;
			this.line = "";
			this.endline = "";
			this.linepos = 0;
			if(this.isred)
				this.red();
		}
		if(!this.isspacing(c))
			this.printchar('\b');
		this.update(this.line + "_");
	}
}
