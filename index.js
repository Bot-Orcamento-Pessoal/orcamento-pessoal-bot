const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');

const app = express();
app.use(bodyParser.json());

// Sua API Key da Gupshup
const API_KEY = 'sk_7b388ebe42994a0585db4a36584741cd';

// Rota de teste
app.get('/', (req, res) => {
    res.send('Bot Orcamento Pessoal está rodando!');
});

// Rota para receber mensagens do Gupshup
app.post('/webhook', async (req, res) => {
    const incomingMessage = req.body;
    console.log('Mensagem recebida:', incomingMessage);

    // Captura o número de quem enviou
    const senderPhoneNumber = incomingMessage.sender.phone;

    // Enviar resposta automática
    try {
        await axios.post('https://api.gupshup.io/sm/api/v1/msg', null, {
            params: {
                channel: 'whatsapp',
                source: '917834811114',
                destination: senderPhoneNumber,
                message: JSON.stringify({ type: "text", text: "Olá! Recebi sua mensagem. Como posso te ajudar?" }),
                src.name: 'OrcamentoPessoalBot'
            },
            headers: {
                'apikey': API_KEY,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        });
        console.log('Mensagem de resposta enviada!');
    } catch (error) {
        console.error('Erro ao enviar resposta:', error.response?.data || error.message);
    }

    res.sendStatus(200);
});

// Ouvindo na porta do Render
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Servidor rodando na porta ${PORT}`);
});
